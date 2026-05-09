from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from utils import extract_symbols, classify_file_role, build_dependency_chain
from issue_parser import extract_issue_entities

logger = logging.getLogger(__name__)

_W_SYMBOL     = 0.20
_W_FILEPATH   = 0.20
_W_DEP        = 0.10
_W_AGREEMENT  = 0.05
_W_RETRIEVAL  = 0.45

assert abs(_W_SYMBOL + _W_FILEPATH + _W_DEP + _W_AGREEMENT + _W_RETRIEVAL - 1.0) < 1e-9

TIER_HIGH       = "HIGH"
TIER_MEDIUM     = "MEDIUM"
TIER_LOW        = "LOW"
TIER_PENALISED  = "PENALISED"

_TIER_THRESHOLDS = [
    (0.55, TIER_HIGH),
    (0.35, TIER_MEDIUM),
    (0.15, TIER_LOW),
]

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
    "init__",
)

_PENALTY_AMOUNT = 0.10

_PENALTY_WAIVE_IF_NAMED = True

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
    "security":    ["security", "oauth", "scope", "scopes", "jwt", "token", "bearer", "apikey", "openid",],
    "dependency":  ["dependency", "dependencies", "depends", "inject", "injection",],
}

_KW_TO_DOMAIN: Dict[str, str] = {}
for _domain, _kws in _FILEPATH_DOMAIN_KEYWORDS.items():
    for _kw in _kws:
        _KW_TO_DOMAIN[_kw] = _domain


@dataclass
class FileRankResult:
    """Full ranking result for a single candidate file."""
    path:              str
    composite_score:   float
    confidence_tier:   str
    retrieval_score:   float
    retrieval_method:  str

    symbol_score:      float = 0.0
    filepath_score:    float = 0.0
    dep_score:         float = 0.0
    agreement_score:   float = 0.0
    penalty:           float = 0.0

    matched_symbols:   List[str] = field(default_factory=list)
    matched_domains:   List[str] = field(default_factory=list)
    dep_path:          List[str] = field(default_factory=list)

    reason:            str = ""

    role:              str = ""
    functions:         List[str] = field(default_factory=list)
    classes:           List[str] = field(default_factory=list)


@dataclass
class RerankerResult:
    """Full output of the reranker — ranked files plus aggregate metadata."""
    ranked_files:      List[FileRankResult]
    confidence_tier:   str
    overall_confidence: float
    anchor_file:       Optional[str]
    low_confidence:    bool
    explanation:       str

def _extract_issue_symbols(issue_full: str) -> Set[str]:
    """
    Extract high-precision code symbols from the issue text.

    Replaces the naive regex-only approach with an engineering-aware parser:
    - Prioritises backticked identifiers and stack trace frames
    - Filters generic prose tokens ("This", "Expected", "Example", "None", ...)
    - Uses confidence thresholds to avoid polluting symbol matches
    """
    entities = extract_issue_entities(issue_full)

    symbols = {
        e.text
        for e in entities
        if e.kind == "symbol" and e.confidence >= 0.60
    }

    symbols |= {
        e.text
        for e in entities
        if e.kind == "error_type" and e.confidence >= 0.75
    }

    return symbols


def _extract_issue_domain_keywords(issue_full: str) -> Set[str]:
    """
    Return which domain keywords from _KW_TO_DOMAIN appear in the issue text.
    Used to match issue → filepath segments.
    """
    text_lower = issue_full.lower()

    kws = {kw for kw in _KW_TO_DOMAIN if kw in text_lower}

    entities = extract_issue_entities(issue_full)
    for e in entities:
        if e.kind != "filepath" or e.confidence < 0.70:
            continue
        fp = e.text.lower().replace("\\", "/")
        parts = re.split(r"[/._\-]", fp)
        for p in parts:
            if p in _KW_TO_DOMAIN:
                kws.add(p)

    return kws


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
    source_matches = {
        sym for sym in issue_symbols
        if re.search(rf"\b{re.escape(sym)}\b", source)
    }

    matched = exact_matches | source_matches
    if not matched:
        return 0.0, []

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
    segments = re.split(r"[/._\-]", fp_lower)
    segment_set = set(segments)

    matched_kws     = issue_domain_kws & segment_set
    matched_domains = list({_KW_TO_DOMAIN[kw] for kw in matched_kws})

    if not matched_kws:
        return 0.0, []

    score = min(1.0, 0.35 * len(matched_domains))

    HIGH_SIGNAL_SEGMENTS = {
      "security",
      "oauth",
      "dependency",
      "dependencies",
      "auth",
      "scope",
      "scopes",
    }

    if any(seg in segment_set for seg in HIGH_SIGNAL_SEGMENTS):
      score += 0.35

    score = min(score, 1.0)
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

    has_penalty_fragment = any(frag in fp_lower for frag in _PENALTY_PATH_FRAGMENTS)
    if not has_penalty_fragment:
        return 0.0

    if _PENALTY_WAIVE_IF_NAMED and file_stem and re.search(rf"\b{re.escape(file_stem)}\b", issue_full, re.IGNORECASE):
        return 0.0

    if (
        fp_lower.startswith("docs")
        or "tutorial" in fp_lower
        or "example" in fp_lower
    ):
      return 0.35

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
    score = max(0.0, raw - penalty)

    if ret >= 0.70:
      score = max(score, 0.45)

    return round(min(score, 1.0), 4)


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

    issue_symbols     = _extract_issue_symbols(issue_full)
    issue_domain_kws  = _extract_issue_domain_keywords(issue_full)

    semantic_hits: Set[str] = {
      fp for fp, (_, m)
      in candidates.items()
      if m in ("semantic", "dependency")
    }

    bm25_hits: Set[str] = {
      fp for fp, (_, m)
      in candidates.items()
      if m in ("bm25", "symbol", "role")
    }

    max_raw = max((s for s, _ in candidates.values()), default=1.0) or 1.0

    logger.debug(
        f"Reranker: {len(candidates)} candidates | "
        f"issue_symbols={issue_symbols} | domain_kws={issue_domain_kws}"
    )

    sym_scores: Dict[str, Tuple[float, List[str]]] = {}
    for fp, (raw, _) in candidates.items():
        src     = sources.get(fp, "")
        symbols = extract_symbols(src)
        s, matched = _symbol_score(symbols, issue_symbols, src)
        sym_scores[fp] = (s, matched)

    anchor_file: Optional[str] = max(sym_scores, key=lambda fp: sym_scores[fp][0]) \
        if sym_scores else None
    if anchor_file and sym_scores[anchor_file][0] == 0.0:
        anchor_file = None

    all_dep_chains: Dict[str, List[str]] = {}
    for fp in candidates:
        all_dep_chains[fp] = build_dependency_chain(fp, sources, max_depth=3)

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
        ret_s = min(raw / max_raw, 1.0)

        if "bm25" in method and fp_s > 0:
          ret_s += 0.15

        ret_s = min(ret_s, 1.0)

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

    results.sort(key=lambda r: (r.confidence_tier == TIER_PENALISED, -r.composite_score))

    non_penalised = [r for r in results if r.confidence_tier != TIER_PENALISED]
    top_results   = (non_penalised if non_penalised else results)[:top_k]

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
