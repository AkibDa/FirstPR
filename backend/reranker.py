"""
reranker.py — Issue-Aware Bug Localization & Relevance Ranking Layer
=====================================================================

This module sits between raw hybrid retrieval (semantic + BM25) and the
reasoning agent.  Its job is to answer one precise question:

    "Given a GitHub issue, which retrieved files are *actually* connected
     to the problem, and with how much confidence?"

It does this with five independent signals, each producing a score in [0, 1]:

    1. Symbol Match   — do class/function names from the issue appear in this file?
    2. Filepath Match — does the file path contain domain keywords from the issue?
    3. Dependency Proximity — how close is this file to a symbol-matched anchor?
    4. Semantic Agreement — do both semantic AND BM25 retrieval agree on this file?
    5. Penalty         — deduct for infrastructure/logging/env/doc files that
                         aren't directly named in the issue.

A weighted composite score is computed, then files are partitioned into
confidence tiers (HIGH / MEDIUM / LOW / PENALISED) with explicit reasoning
strings that the reasoning agent can show to the user.

All computation is zero-LLM-cost: pure Python regex + set operations.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from utils import extract_symbols, classify_file_role, build_dependency_chain

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuneable weights  (must sum to 1.0)
# ---------------------------------------------------------------------------
_W_SYMBOL     = 0.35   # strongest signal: name mentioned in issue ↔ file
_W_FILEPATH   = 0.25   # second: path semantics match issue domain
_W_DEP        = 0.15   # third: dependency proximity to anchor file
_W_AGREEMENT  = 0.15   # fourth: both retrieval methods agree
_W_RETRIEVAL  = 0.10   # base retrieval score (normalised), tie-breaker

assert abs(_W_SYMBOL + _W_FILEPATH + _W_DEP + _W_AGREEMENT + _W_RETRIEVAL - 1.0) < 1e-9

# ---------------------------------------------------------------------------
# Confidence tiers
# ---------------------------------------------------------------------------
TIER_HIGH       = "HIGH"       # composite ≥ 0.55
TIER_MEDIUM     = "MEDIUM"     # composite ≥ 0.35
TIER_LOW        = "LOW"        # composite ≥ 0.15
TIER_PENALISED  = "PENALISED"  # net score < 0.15 after penalty

_TIER_THRESHOLDS = [
    (0.55, TIER_HIGH),
    (0.35, TIER_MEDIUM),
    (0.15, TIER_LOW),
]

# ---------------------------------------------------------------------------
# Penalty targets — infrastructure files that should not rank unless named
# ---------------------------------------------------------------------------

# Path fragments that suggest low-signal infrastructure
_PENALTY_PATH_FRAGMENTS: Tuple[str, ...] = (
    "log", "logger", "logging",
    "env", "environ", "environment",
    "sys_info", "sysinfo", "system_info",
    "telemetry", "metrics", "monitor",
    "debug", "trace",
    "setup", "install", "bootstrap",
    "constant", "consts",
    "exception", "error_handler",
    "compat", "compatibility",
    "deprecat",
    "version",
    "health",
    "ping",
    "init__",         # __init__ files with nothing but imports
)

# Base penalty applied when a file matches any fragment above
_PENALTY_AMOUNT = 0.25

# If the issue text directly names the file stem, the penalty is waived
_PENALTY_WAIVE_IF_NAMED = True

# ---------------------------------------------------------------------------
# Filepath keyword sets — grouped by domain so we can match issue domain → path
# ---------------------------------------------------------------------------

_FILEPATH_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "tool":        ["tool", "tools", "plugin", "extension", "adapter"],
    "runtime":     ["runtime", "runner", "executor", "engine", "worker", "process"],
    "config":      ["config", "configuration", "setting", "option", "param"],
    "middleware":  ["middleware", "intercept", "hook", "proxy", "wrapper"],
    "auth":        ["auth", "authn", "authz", "permission", "role", "token", "oauth"],
    "api":         ["api", "route", "router", "endpoint", "handler", "view", "controller"],
    "model":       ["model", "schema", "entity", "orm", "db", "database", "migration"],
    "service":     ["service", "usecase", "manager", "orchestrat"],
    "cache":       ["cache", "redis", "memcache", "store"],
    "queue":       ["queue", "task", "worker", "job", "celery", "broker"],
    "parser":      ["parse", "parser", "lexer", "ast", "tokenize", "transform"],
    "serializer":  ["serial", "deserial", "codec", "marshal", "encode", "decode"],
    "client":      ["client", "http", "request", "fetch", "conn", "socket"],
    "test":        ["test", "spec", "mock", "fixture", "stub"],
    "util":        ["util", "helper", "common", "shared", "misc"],
}

# Flatten to a lookup: keyword → domain
_KW_TO_DOMAIN: Dict[str, str] = {}
for _domain, _kws in _FILEPATH_DOMAIN_KEYWORDS.items():
    for _kw in _kws:
        _KW_TO_DOMAIN[_kw] = _domain


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FileRankResult:
    """Full ranking result for a single candidate file."""
    path:              str
    composite_score:   float            # final weighted score in [0, 1] (before penalty clip)
    confidence_tier:   str              # HIGH / MEDIUM / LOW / PENALISED
    retrieval_score:   float            # raw score from retrieval (semantic or bm25)
    retrieval_method:  str              # "semantic" | "bm25" | "both"

    # Per-signal scores (all in [0, 1])
    symbol_score:      float = 0.0
    filepath_score:    float = 0.0
    dep_score:         float = 0.0
    agreement_score:   float = 0.0
    penalty:           float = 0.0

    # Matched evidence (for the reasoning agent to cite)
    matched_symbols:   List[str] = field(default_factory=list)
    matched_domains:   List[str] = field(default_factory=list)
    dep_path:          List[str] = field(default_factory=list)  # hop chain to anchor

    # Human-readable reason string
    reason:            str = ""

    # Structural metadata (passed through from retrieval)
    role:              str = ""
    functions:         List[str] = field(default_factory=list)
    classes:           List[str] = field(default_factory=list)


@dataclass
class RerankerResult:
    """Full output of the reranker — ranked files plus aggregate metadata."""
    ranked_files:      List[FileRankResult]
    confidence_tier:   str          # tier of the TOP file
    overall_confidence: float       # composite score of the top file
    anchor_file:       Optional[str]  # file with the highest symbol match
    low_confidence:    bool         # True if even the best file is LOW/PENALISED
    explanation:       str          # human-readable summary for the reasoning agent


# ---------------------------------------------------------------------------
# Signal computers
# ---------------------------------------------------------------------------

def _extract_issue_symbols(issue_full: str) -> Set[str]:
    """
    Extract CamelCase identifiers and snake_case names from the issue text.

    Examples: "ToolRuntime", "with_config", "AgentExecutor"
    Minimum length 4 to filter noise.
    """
    # CamelCase / PascalCase
    camel = re.findall(r"\b[A-Z][a-zA-Z0-9]{3,}\b", issue_full)
    # snake_case (at least one underscore, each segment ≥ 2 chars)
    snake = re.findall(r"\b[a-z][a-z0-9]{1,}(?:_[a-z0-9]{2,})+\b", issue_full)
    # All-caps acronyms like "LLM", "API" are already in camel via the pattern
    return set(camel + snake)


def _extract_issue_domain_keywords(issue_full: str) -> Set[str]:
    """
    Return which domain keywords from _KW_TO_DOMAIN appear in the issue text.
    Used to match issue → filepath segments.
    """
    text_lower = issue_full.lower()
    return {kw for kw in _KW_TO_DOMAIN if kw in text_lower}


def _symbol_score(
    file_symbols: Dict[str, List[str]],
    issue_symbols: Set[str],
    source: str,
) -> Tuple[float, List[str]]:
    """
    Score in [0, 1] based on how many issue symbols appear in this file.

    Checks:
    - Class/function name exact match with extracted symbols
    - Substring search in full source (catches attribute access, comments, etc.)

    Returns (score, list_of_matched_symbol_strings).
    """
    if not issue_symbols:
        return 0.0, []

    all_file_symbols: Set[str] = (
        set(file_symbols.get("functions", [])) |
        set(file_symbols.get("classes", []))
    )

    exact_matches = issue_symbols & all_file_symbols
    # Also check source text substring (case-sensitive, whole-word)
    source_matches = {
        sym for sym in issue_symbols
        if re.search(rf"\b{re.escape(sym)}\b", source)
    }

    matched = exact_matches | source_matches
    if not matched:
        return 0.0, []

    # Score: log-scaled so 1 match → 0.4, 2 → 0.65, 3+ → ~0.85+
    import math
    score = min(1.0, 0.4 + 0.3 * math.log2(len(matched)))
    return round(score, 3), sorted(matched)


def _filepath_score(
    file_path: str,
    issue_domain_kws: Set[str],
) -> Tuple[float, List[str]]:
    """
    Score in [0, 1] based on whether file path segments match issue domain.

    Returns (score, matched_domains).
    """
    fp_lower = file_path.lower().replace("\\", "/")
    # Split on common separators so "tool_runtime" → ["tool", "runtime"]
    segments = re.split(r"[/._\-]", fp_lower)
    segment_set = set(segments)

    matched_kws     = issue_domain_kws & segment_set
    matched_domains = list({_KW_TO_DOMAIN[kw] for kw in matched_kws})

    if not matched_kws:
        return 0.0, []

    # Each distinct domain hit adds 0.4, capped at 1.0
    score = min(1.0, 0.4 * len(matched_domains))
    return round(score, 3), matched_domains


def _dependency_score(
    file_path: str,
    anchor_file: Optional[str],
    sources: Dict[str, str],
    all_dep_chains: Dict[str, List[str]],
) -> Tuple[float, List[str]]:
    """
    Score in [0, 1] based on how close this file is to the anchor file
    in the import/dependency graph.

    - Direct import of anchor (or anchor imports this): 1.0
    - 1 hop away:                                        0.6
    - 2 hops away:                                       0.3
    - Not reachable within 3 hops:                       0.0
    """
    if not anchor_file or file_path == anchor_file:
        return 0.0, []

    # Check if anchor's dep chain contains an edge mentioning this file
    anchor_chain = all_dep_chains.get(anchor_file, [])
    for edge in anchor_chain:
        parts = [p.strip() for p in edge.split("→")]
        if file_path in parts:
            hop = anchor_chain.index(edge)
            if hop == 0:
                return 1.0, [edge]
            elif hop <= 2:
                return 0.6, [edge]
            else:
                return 0.3, [edge]

    # Reverse: does this file's dep chain reach the anchor?
    this_chain = all_dep_chains.get(file_path, [])
    for edge in this_chain:
        parts = [p.strip() for p in edge.split("→")]
        if anchor_file in parts:
            hop = this_chain.index(edge)
            if hop == 0:
                return 1.0, [edge]
            elif hop <= 2:
                return 0.6, [edge]

    return 0.0, []


def _agreement_score(
    file_path: str,
    semantic_hits: Set[str],
    bm25_hits: Set[str],
) -> float:
    """
    Score 1.0 if both semantic and BM25 retrieved this file; 0.0 otherwise.
    Agreement is the strongest cross-validation signal we have.
    """
    in_semantic = file_path in semantic_hits
    in_bm25     = file_path in bm25_hits
    if in_semantic and in_bm25:
        return 1.0
    return 0.0


def _penalty_score(
    file_path: str,
    issue_full: str,
) -> float:
    """
    Return a penalty amount (subtracted from composite) for infrastructure files.

    Waived entirely if the file stem is explicitly mentioned in the issue text.
    """
    fp_lower  = file_path.lower().replace("\\", "/")
    file_stem = re.split(r"[/.]", fp_lower)[-2] if "." in fp_lower.split("/")[-1] else fp_lower.split("/")[-1]

    # Check if any penalty fragment matches
    has_penalty_fragment = any(frag in fp_lower for frag in _PENALTY_PATH_FRAGMENTS)
    if not has_penalty_fragment:
        return 0.0

    # Waive if the stem is directly named in the issue
    if _PENALTY_WAIVE_IF_NAMED and file_stem and re.search(rf"\b{re.escape(file_stem)}\b", issue_full, re.IGNORECASE):
        return 0.0

    return _PENALTY_AMOUNT


def _composite(
    sym: float,
    fp:  float,
    dep: float,
    agr: float,
    ret: float,
    penalty: float,
) -> float:
    """Compute weighted composite and apply penalty floor."""
    raw = (
        _W_SYMBOL    * sym +
        _W_FILEPATH  * fp  +
        _W_DEP       * dep +
        _W_AGREEMENT * agr +
        _W_RETRIEVAL * ret
    )
    return max(0.0, round(raw - penalty, 4))


def _assign_tier(composite: float) -> str:
    for threshold, tier in _TIER_THRESHOLDS:
        if composite >= threshold:
            return tier
    return TIER_PENALISED


def _build_reason(result: FileRankResult) -> str:
    """Construct a concise, evidence-backed reason string for the reasoning agent."""
    parts: List[str] = []

    if result.matched_symbols:
        sym_list = ", ".join(f"`{s}`" for s in result.matched_symbols[:4])
        parts.append(f"Issue symbols found in file: {sym_list}")

    if result.matched_domains:
        parts.append(f"File path matches issue domain(s): {', '.join(result.matched_domains)}")

    if result.dep_path:
        parts.append(f"Dependency link: {result.dep_path[0]}")

    if result.agreement_score == 1.0:
        parts.append("Confirmed by both semantic and keyword retrieval")

    if result.penalty > 0:
        parts.append(f"⚠ Infrastructure penalty applied ({result.penalty:.2f})")

    if not parts:
        parts.append(f"{result.retrieval_method.capitalize()} retrieval match "
                     f"(score {result.retrieval_score:.2f})")

    tier_tag = {
        TIER_HIGH:      "✅ HIGH confidence",
        TIER_MEDIUM:    "🟡 MEDIUM confidence",
        TIER_LOW:       "🔶 LOW confidence",
        TIER_PENALISED: "❌ Likely unrelated (penalised)",
    }.get(result.confidence_tier, "")

    return f"[{tier_tag}] " + " | ".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def rerank(
    candidates: Dict[str, Tuple[float, str]],   # path → (raw_score, method)
    sources:    Dict[str, str],
    issue_full: str,
    top_k:      int = 6,
) -> RerankerResult:
    """
    Rerank candidate files using five issue-aware signals.

    Parameters
    ----------
    candidates : dict
        Raw retrieval results: {file_path: (raw_score, "semantic"|"bm25")}
    sources : dict
        Full source code map from the engine bundle.
    issue_full : str
        Complete issue text (title + body).
    top_k : int
        Maximum number of files to return (post-reranking).

    Returns
    -------
    RerankerResult
        Ranked files with per-signal scores, tiers, and a summary.
    """
    if not candidates:
        return RerankerResult(
            ranked_files=[],
            confidence_tier=TIER_PENALISED,
            overall_confidence=0.0,
            anchor_file=None,
            low_confidence=True,
            explanation="No candidate files were retrieved.",
        )

    # --- Pre-compute issue signals (once, shared across all files) ---
    issue_symbols     = _extract_issue_symbols(issue_full)
    issue_domain_kws  = _extract_issue_domain_keywords(issue_full)

    # Separate retrieval method sets for agreement scoring
    semantic_hits: Set[str] = {fp for fp, (_, m) in candidates.items() if m == "semantic"}
    bm25_hits:     Set[str] = {fp for fp, (_, m) in candidates.items() if m == "bm25"}

    # Normalise raw retrieval scores to [0, 1] relative to this candidate set
    max_raw = max((s for s, _ in candidates.values()), default=1.0) or 1.0

    logger.debug(
        f"Reranker: {len(candidates)} candidates | "
        f"issue_symbols={issue_symbols} | domain_kws={issue_domain_kws}"
    )

    # --- First pass: compute symbol scores to identify the anchor file ---
    sym_scores: Dict[str, Tuple[float, List[str]]] = {}
    for fp, (raw, _) in candidates.items():
        src     = sources.get(fp, "")
        symbols = extract_symbols(src)
        s, matched = _symbol_score(symbols, issue_symbols, src)
        sym_scores[fp] = (s, matched)

    # Anchor = file with the highest symbol match score
    anchor_file: Optional[str] = max(sym_scores, key=lambda fp: sym_scores[fp][0]) \
        if sym_scores else None
    if anchor_file and sym_scores[anchor_file][0] == 0.0:
        anchor_file = None   # no file has any symbol match → no meaningful anchor

    # --- Pre-compute dependency chains for all candidates ---
    all_dep_chains: Dict[str, List[str]] = {}
    for fp in candidates:
        all_dep_chains[fp] = build_dependency_chain(fp, sources, max_depth=3)

    # --- Second pass: compute all signals and build FileRankResult objects ---
    results: List[FileRankResult] = []

    for fp, (raw, method) in candidates.items():
        src     = sources.get(fp, "")
        symbols = extract_symbols(src)
        role    = classify_file_role(fp, src)

        sym_s, matched_syms  = sym_scores[fp]
        fp_s,  matched_doms  = _filepath_score(fp, issue_domain_kws)
        dep_s, dep_path      = _dependency_score(fp, anchor_file, sources, all_dep_chains)
        agr_s                = _agreement_score(fp, semantic_hits, bm25_hits)
        pen                  = _penalty_score(fp, issue_full)
        ret_s                = raw / max_raw

        comp = _composite(sym_s, fp_s, dep_s, agr_s, ret_s, pen)
        tier = _assign_tier(comp)

        r = FileRankResult(
            path              = fp,
            composite_score   = comp,
            confidence_tier   = tier,
            retrieval_score   = raw,
            retrieval_method  = "both" if fp in semantic_hits and fp in bm25_hits else method,
            symbol_score      = sym_s,
            filepath_score    = fp_s,
            dep_score         = dep_s,
            agreement_score   = agr_s,
            penalty           = pen,
            matched_symbols   = matched_syms,
            matched_domains   = matched_doms,
            dep_path          = dep_path,
            role              = role,
            functions         = symbols.get("functions", []),
            classes           = symbols.get("classes", []),
        )
        r.reason = _build_reason(r)
        results.append(r)

    # --- Sort: composite descending, then penalised files last ---
    results.sort(key=lambda r: (r.confidence_tier == TIER_PENALISED, -r.composite_score))

    # Exclude PENALISED files from the top-k unless we have nothing better
    non_penalised = [r for r in results if r.confidence_tier != TIER_PENALISED]
    top_results   = (non_penalised if non_penalised else results)[:top_k]

    # --- Build aggregate metadata ---
    top_score  = top_results[0].composite_score if top_results else 0.0
    top_tier   = top_results[0].confidence_tier if top_results else TIER_PENALISED
    low_conf   = top_tier in (TIER_LOW, TIER_PENALISED)

    if low_conf:
        explanation = (
            "⚠ Low-confidence localisation: the retrieved files show weak "
            "connection to the issue symbols and domain. The reasoning below "
            "may be imprecise. Consider providing more issue context or checking "
            f"whether the repository has been fully indexed. "
            f"Best match: {top_results[0].path if top_results else 'none'} "
            f"(composite={top_score:.2f})."
        )
    elif top_tier == TIER_MEDIUM:
        explanation = (
            f"🟡 Medium-confidence localisation. Top file '{top_results[0].path}' "
            f"is likely relevant but other candidates may also be involved. "
            f"Composite score: {top_score:.2f}."
        )
    else:
        top_syms = top_results[0].matched_symbols[:3]
        explanation = (
            f"✅ High-confidence localisation. '{top_results[0].path}' "
            f"contains issue symbols {top_syms} and matches the expected domain. "
            f"Composite score: {top_score:.2f}."
        )

    return RerankerResult(
        ranked_files       = top_results,
        confidence_tier    = top_tier,
        overall_confidence = top_score,
        anchor_file        = anchor_file,
        low_confidence     = low_conf,
        explanation        = explanation,
    )