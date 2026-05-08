import re
import logging
import httpx
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

def validate_github_url(url: str) -> bool:
    """Return True if *url* looks like a GitHub repository URL."""
    return url.startswith(("https://github.com/", "http://github.com/"))

def get_repo_name(url: str) -> str:
    """Extract the bare repository name from a GitHub URL."""
    return url.rstrip("/").split("/")[-1].replace(".git", "")

def parse_github_issue_url(url: str) -> Optional[Tuple[str, str, str]]:
    """
    Parse a GitHub issue URL and return (owner, repo, issue_number).

    Accepts:
        https://github.com/owner/repo/issues/42
        https://github.com/owner/repo/issues/42#issuecomment-...
    Returns None if the URL does not match the expected pattern.
    """
    pattern = r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)"
    m = re.match(pattern, url.split("#")[0].rstrip("/"))
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None

async def fetch_github_issue(issue_url: str) -> Dict[str, str]:
    """
    Fetch a GitHub issue's title and body via the public REST API.

    Returns a dict with keys ``title``, ``body``, ``labels``, and ``number``.
    Raises ``ValueError`` on bad URL; raises ``httpx.HTTPError`` on network /
    API failures.
    """
    parsed = parse_github_issue_url(issue_url)
    if not parsed:
        raise ValueError(f"Not a valid GitHub issue URL: {issue_url!r}")

    owner, repo, number = parsed
    api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    headers = {"Accept": "application/vnd.github+json"}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(api_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return {
        "title":  data.get("title", ""),
        "body":   data.get("body", "") or "",
        "labels": [lbl["name"] for lbl in data.get("labels", [])],
        "number": number,
    }

_IMPORT_RE = re.compile(
    r"""
    (?:^|\n)
    (?:
        from\s+([\w.]+)\s+import[^\n]*
      | import\s+([\w.][^\n,]*)
    )
    """,
    re.VERBOSE,
)

def extract_imports(source: str) -> List[str]:
    """Return a deduplicated list of top-level module names imported in *source*."""
    modules: List[str] = []
    for m in _IMPORT_RE.finditer(source):
        if m.group(1):
            modules.append(m.group(1).split(".")[0])
        elif m.group(2):
            for part in m.group(2).split(","):
                modules.append(part.strip().split(".")[0])
    return list(dict.fromkeys(mod for mod in modules if mod))

_FUNC_RE  = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*[:(]",          re.MULTILINE)

def extract_symbols(source: str) -> Dict[str, List[str]]:
    """Return ``{"functions": [...], "classes": [...]}`` found in *source*."""
    return {
        "functions": _FUNC_RE.findall(source),
        "classes":   _CLASS_RE.findall(source),
    }

def classify_file_role(file_path: str, source: str) -> str:
    """Heuristically classify a file's architectural role."""
    fp = file_path.lower()
    if any(fp.endswith(s) for s in ("main.py", "app.py", "server.py", "run.py")):
        return "entry-point"
    if any(kw in fp for kw in ("model", "schema", "entity", "orm")):
        return "model"
    if any(kw in fp for kw in ("route", "view", "api", "controller", "handler")):
        return "route"
    if any(kw in fp for kw in ("service", "usecase", "manager")):
        return "service"
    if any(kw in fp for kw in ("util", "helper", "common", "shared")):
        return "utility"
    if any(kw in fp for kw in ("test", "spec")):
        return "test"
    if any(kw in fp for kw in ("config", "setting", "env")):
        return "config"
    if "BaseModel" in source or "dataclass" in source:
        return "model"
    if "@router" in source or "@app" in source:
        return "route"
    return "module"

def build_dependency_chain(
    file_path: str,
    all_sources: Dict[str, str],
    max_depth: int = 3,
) -> List[str]:
    """
    Trace the import chain starting from *file_path* up to *max_depth* hops.

    *all_sources* maps file-path → source text.
    Returns an ordered list of edge strings like ["app.py → model.py"].
    Only local imports (files that exist as keys in *all_sources*) are followed.
    """
    module_to_path: Dict[str, str] = {}
    for fp in all_sources:
        without_ext = fp[:-3] if fp.endswith(".py") else fp
        module_to_path[without_ext.replace("/", ".").replace("\\", ".")] = fp
        stem = without_ext.split("/")[-1].split("\\")[-1]
        module_to_path.setdefault(stem, fp)

    chain:   List[str] = []
    visited: set       = set()

    def _trace(fp: str, depth: int) -> None:
        if depth > max_depth or fp in visited:
            return
        visited.add(fp)
        src = all_sources.get(fp, "")
        for mod in extract_imports(src):
            candidate_fp: Optional[str] = None
            for key in (mod, mod.split(".")[-1]):
                if key in module_to_path and module_to_path[key] != fp:
                    candidate_fp = module_to_path[key]
                    break
            if candidate_fp:
                edge = f"{fp} → {candidate_fp}"
                if edge not in chain:
                    chain.append(edge)
                _trace(candidate_fp, depth + 1)

    _trace(file_path, 0)
    return chain
