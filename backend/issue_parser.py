from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Literal, Optional, Sequence, Set

EntityKind = Literal[
    "symbol",        # class/function/var (ToolRuntime, with_config, RunnableConfig)
    "filepath",      # src/foo/bar.py, packages/mod.rs, etc.
    "error_type",    # ValueError, TypeError, ToolRuntimeError
    "module",        # package.module (python/js/go-ish dotted)
]

@dataclass(frozen=True)
class IssueEntity:
    text: str
    kind: EntityKind
    confidence: float          # 0..1
    evidence: str              # short human-readable source tag

_GENERIC_TOKENS: Set[str] = {
    # Common issue prose
    "This", "That", "These", "Those",
    "Expected", "Actual", "Example", "Examples",
    "Repro", "Reproduction", "Steps", "Step",
    "Result", "Results", "Output", "Input",
    "Note", "Notes",
    "None", "Null", "True", "False",
    "Error", "Errors", "Exception", "Exceptions",
    "Stack", "Trace", "Traceback",
    "Windows", "Linux", "Mac", "MacOS", "Darwin",
    "Version", "Versions",
    "Issue", "Bug", "Fix",
}

_GENERIC_LOWER: Set[str] = {t.lower() for t in _GENERIC_TOKENS}

def _is_generic(token: str) -> bool:
    if not token:
        return True
    if token.lower() in _GENERIC_LOWER:
        return True
    # Single-letter or mostly punctuation
    if len(token) <= 1:
        return True
    return False

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x

_BACKTICK_RE = re.compile(r"`([^`\n]{1,128})`")

# Conservative: symbols that look like identifiers (no spaces)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_CAMEL_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}\b")  # allow len>=3, filtered later
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]{1,}(?:_[a-z0-9]{2,})+\b")

_DOTTED_MODULE_RE = re.compile(r"\b[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){1,}\b")

# File paths: keep wide; URL filtering is done post-match (Python re forbids
# variable-width lookbehinds like (?<!https?://)).
_FILEPATH_RE = re.compile(
    r"""
    (?:
      (?:[A-Za-z]:\\)?            # optional windows drive
      (?:[~./\\]|[A-Za-z0-9_])    # leading char
      [A-Za-z0-9_\-./\\]{1,240}   # body
      \.(?:py|pyi|ts|tsx|js|jsx|go|rs|java|kt|c|cc|cpp|h|hpp|rb|php|cs)
    )
    """,
    re.VERBOSE,
)

_PY_TRACE_FRAME_RE = re.compile(
    r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+([A-Za-z_][A-Za-z0-9_]*)'
)

_JS_TRACE_FRAME_RE = re.compile(
    r"\bat\s+(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(([^)]+):(\d+):(\d+)\)"
)

_ERROR_TYPE_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*Error|[A-Z][A-Za-z0-9_]*Exception)\b")

def extract_issue_entities(issue_text: str) -> List[IssueEntity]:
    """
    Extract entities from issue text. Returns a deduplicated, confidence-sorted list.

    Confidence heuristics (high → low):
    - backticked identifiers/paths
    - stack trace frames (function + path)
    - explicit Error/Exception type tokens
    - remaining CamelCase/snake_case identifiers (after generic filtering)
    """
    if not issue_text:
        return []

    entities: List[IssueEntity] = []

    # 1) Backticked chunks — high precision
    for raw in _BACKTICK_RE.findall(issue_text):
        t = raw.strip()
        if not t or len(t) > 128:
            continue
        if _IDENT_RE.match(t) and not _is_generic(t):
            entities.append(IssueEntity(text=t, kind="symbol", confidence=0.95, evidence="backticked"))
        else:
            # Might be a file path, module, or code-like token
            if _FILEPATH_RE.search(t):
                fp = _FILEPATH_RE.search(t).group(0)
                if "://" not in fp:
                    entities.append(IssueEntity(text=fp, kind="filepath", confidence=0.95, evidence="backticked"))
            elif _DOTTED_MODULE_RE.match(t):
                entities.append(IssueEntity(text=t, kind="module", confidence=0.85, evidence="backticked"))

    # 2) Stack traces
    for m in _PY_TRACE_FRAME_RE.finditer(issue_text):
        path, _line, func = m.group(1), m.group(2), m.group(3)
        if path:
            entities.append(IssueEntity(text=path, kind="filepath", confidence=0.92, evidence="py-trace"))
        if func and not _is_generic(func):
            entities.append(IssueEntity(text=func, kind="symbol", confidence=0.92, evidence="py-trace"))

    for m in _JS_TRACE_FRAME_RE.finditer(issue_text):
        func, path, _line, _col = m.group(1), m.group(2), m.group(3), m.group(4)
        if path:
            entities.append(IssueEntity(text=path, kind="filepath", confidence=0.90, evidence="js-trace"))
        if func and not _is_generic(func):
            entities.append(IssueEntity(text=func, kind="symbol", confidence=0.90, evidence="js-trace"))

    # 3) Error types
    for err in _ERROR_TYPE_RE.findall(issue_text):
        if not _is_generic(err):
            entities.append(IssueEntity(text=err, kind="error_type", confidence=0.80, evidence="error-type"))

    # 4) Filepaths outside backticks/traces
    for fp in _FILEPATH_RE.findall(issue_text):
        fp2 = fp.strip()
        if fp2 and "://" not in fp2:
            entities.append(IssueEntity(text=fp2, kind="filepath", confidence=0.70, evidence="filepath"))

    # 5) Remaining symbols (CamelCase / snake_case)
    for sym in _CAMEL_RE.findall(issue_text):
        if _is_generic(sym):
            continue
        # Downweight very short CamelCase (e.g., Api) and obvious English words
        conf = 0.55 if len(sym) >= 5 else 0.40
        entities.append(IssueEntity(text=sym, kind="symbol", confidence=conf, evidence="camel"))

    for sym in _SNAKE_RE.findall(issue_text):
        if _is_generic(sym):
            continue
        entities.append(IssueEntity(text=sym, kind="symbol", confidence=0.60, evidence="snake"))

    # 6) Dotted modules (can be noisy; keep lower confidence)
    for mod in _DOTTED_MODULE_RE.findall(issue_text):
        if any(mod.startswith(p) for p in ("http.", "https.")):
            continue
        # Avoid capturing sentences like "e.g.this.that" – require at least one capital or underscore OR common module-ish lowercase
        if len(mod) < 6:
            continue
        entities.append(IssueEntity(text=mod, kind="module", confidence=0.45, evidence="dotted"))

    return _dedupe_and_sort(entities)

def _dedupe_and_sort(entities: Sequence[IssueEntity]) -> List[IssueEntity]:
    """
    Dedupe by (kind, lower(text)) keeping highest-confidence instance.
    Sort by confidence desc then shorter evidence.
    """
    best = {}
    for e in entities:
        key = (e.kind, e.text.lower())
        prev = best.get(key)
        if prev is None or e.confidence > prev.confidence:
            best[key] = IssueEntity(
                text=e.text,
                kind=e.kind,
                confidence=_clamp01(float(e.confidence)),
                evidence=e.evidence,
            )

    out = list(best.values())
    out.sort(key=lambda x: (-x.confidence, x.kind, len(x.text)))
    return out

def top_symbols(entities: Iterable[IssueEntity], *, min_conf: float = 0.60) -> List[str]:
    """Convenience: return symbol texts above confidence threshold."""
    return [e.text for e in entities if e.kind == "symbol" and e.confidence >= min_conf]

def top_filepaths(entities: Iterable[IssueEntity], *, min_conf: float = 0.70) -> List[str]:
    """Convenience: return filepath texts above confidence threshold."""
    return [e.text for e in entities if e.kind == "filepath" and e.confidence >= min_conf]
