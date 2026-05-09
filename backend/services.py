from __future__ import annotations

import hashlib
from config import settings
import asyncio
import json
import logging
import re
import time
import torch
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from llama_index.llms.ollama import Ollama
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings, Document
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeWithScore

import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

from rank_bm25 import BM25Okapi

from utils import (
    extract_imports,
    extract_symbols,
    classify_file_role,
    build_dependency_chain,
)
from reranker import rerank
from issue_parser import extract_issue_entities

logger = logging.getLogger(__name__)

repo_cache: Dict[str, dict] = {}

CHROMA_DIR = Path("./chroma_db")
CHROMA_DIR.mkdir(exist_ok=True)
_chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

device = (
    "cuda" if torch.cuda.is_available()
    else "mps" if torch.backends.mps.is_available()
    else "cpu"
)

if settings.is_production:
    logger.info("Using Remote Embedding Server")

    from llama_index.embeddings.openai_like import OpenAILikeEmbedding

    Settings.embed_model = OpenAILikeEmbedding(
        model_name=settings.embed_model,
        api_base=settings.cloud_embed_url,
        api_key="dummy-key",
        embed_batch_size=settings.embed_batch_size,
    )
    logger.info(f"Embedding URL: {settings.cloud_embed_url}")

else:
    logger.info(f"Using Local Embedding Device: {device}")

    Settings.embed_model = HuggingFaceEmbedding(
        model_name=settings.embed_model,
        device=device,
        embed_batch_size=settings.embed_batch_size,
    )

if settings.is_production:
    logger.info("Using Remote AMD GPU vLLM Inference")

    Settings.llm = OpenAI(
        model=settings.llm_model,
        api_key="dummy-key",
        api_base=settings.llm_base_url,
        request_timeout=float(settings.llm_timeout),
        max_tokens=2048,
        additional_kwargs={"stop": ["```"]},
    )
    logger.info(f"LLM URL: {settings.llm_base_url}")

else:
    logger.info("Using Local Ollama Inference")

    Settings.llm = Ollama(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        request_timeout=float(settings.llm_timeout),
        context_window=16384,
    )

_IGNORE_DIRS: frozenset[str] = frozenset({
    "test", "tests", "__tests__", "spec", "specs",
    "docs", "doc", "documentation",
    "examples", "example", "demo", "demos", "sample", "samples",
    "notebooks", "notebook",
    "benchmark", "benchmarks",
    "migrations", "locale", "locales", "i18n",
    "vendor", "node_modules", ".git", ".github",
    "dist", "build", "out", "target", "bin", "obj",
    "static", "assets", "public", "media",
    "coverage", "htmlcov", ".tox", ".mypy_cache", "__pycache__",
})

_IGNORE_EXTS: frozenset[str] = frozenset({
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".lock", ".sum",           # lockfiles
    ".csv", ".tsv",            # tabular data
    ".json",                   # usually config/fixtures, not logic
    ".min.js", ".map",         # minified / sourcemaps
    ".md", ".rst", ".txt",     # prose docs
    ".ipynb",                  # notebooks
    ".pb", ".onnx", ".pt", ".pth",  # model weights
    ".whl", ".egg",
    ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env",
    ".css", ".scss", ".less",
    ".html", ".htm",
    ".xml",
    ".sh", ".bat", ".ps1",
})

# Files whose names signal low value regardless of extension
_IGNORE_NAME_PATTERNS: Tuple[str, ...] = (
    "setup.py", "setup.cfg", "pyproject.toml",
    "requirements.txt", "requirements-dev.txt",
    "conftest.py", "pytest.ini",
    "Makefile", "Dockerfile", ".dockerignore",
    "CHANGELOG", "CHANGES", "HISTORY",
    "LICENSE", "LICENCE", "NOTICE", "AUTHORS", "CONTRIBUTORS",
    "package.json", "package-lock.json", "yarn.lock",
    "tsconfig.json", "eslint", "prettier", ".editorconfig",
)

# Preferred source directories — files here get priority embedding slots
_CORE_DIR_HINTS: frozenset[str] = frozenset({
    "src", "lib", "core", "app", "api", "server",
    "pkg", "internal", "backend", "service", "services",
    "handler", "handlers", "controller", "controllers",
    "model", "models", "schema", "schemas",
    "router", "routers", "route", "routes",
    "util", "utils", "helper", "helpers",
    "middleware",
})

ARCHITECTURE_QUERIES = [
    "change model",
    "where can i change",
    "deepfake model",
    "different model",
    "which model",
    "model used",
    "where is the model",
    "inference pipeline",
    "how does inference work",
    "where is prediction done",
    "where is detection done",
]

MODEL_KEYWORDS = [
    "torch.load",
    "load_model",
    "state_dict",
    "EfficientNet",
    "ResNet",
    "Xception",
    "MesoNet",
    "from_pretrained",
    "AutoModel",
    "predict",
    "inference",
    "classifier",
    "weights",
    ".pth",
    ".pt",
    ".onnx",
    "model =",
    "DeepFake",
    "deepfake",
    "detect",
]

# Hard limit: never embed more than this many files per repo
_MAX_EMBED_FILES = 300
# Hard limit: files larger than this char count are chunked more aggressively
_LARGE_FILE_THRESHOLD = 8_000


def _should_skip_file(file_path: str) -> bool:
    """
    Return True if the file should be excluded from embedding entirely.

    Decision is based on path components (directory names), file extension,
    and known low-value filenames — all evaluated without reading the file.
    """
    fp_lower = file_path.lower().replace("\\", "/")
    parts = fp_lower.split("/")

    # Skip if any directory segment is in the ignore list
    if any(p in _IGNORE_DIRS for p in parts[:-1]):
        return True

    # Skip by extension
    for ext in _IGNORE_EXTS:
        if fp_lower.endswith(ext):
            return True

    # Skip by filename pattern
    basename = parts[-1]
    if any(basename.startswith(pat.lower()) for pat in _IGNORE_NAME_PATTERNS):
        return True

    return False


def _file_priority(file_path: str) -> int:
    """
    Return a priority score (lower = more important) for ordering files.

    Core source files get 0-1, utility/schema files get 2, test-adjacent or
    config files that slipped through filtering get 3.
    """
    fp_lower = file_path.lower().replace("\\", "/")
    parts = fp_lower.split("/")

    if any(p in _CORE_DIR_HINTS for p in parts):
        return 0

    stem = parts[-1].replace(".py", "").replace(".ts", "").replace(".js", "")
    if any(hint in stem for hint in ("main", "app", "server", "run", "index")):
        return 0
    if any(hint in stem for hint in ("util", "helper", "schema", "model", "service")):
        return 1
    if any(hint in stem for hint in ("config", "setting")):
        return 2

    return 3


def _split_repo_content(content: str) -> List[Tuple[str, str]]:
    """
    Split the gitingest content blob into (file_path, source_code) pairs,
    applying aggressive intelligent filtering and priority-based capping.
    """
    parts = re.split(r"={48}\n(?:File|FILE|file):\s*", content)

    raw_files: List[Tuple[str, str]] = []
    for part in parts:
        if not part.strip() or "Directory structure:" in part:
            continue
        subparts = part.split("\n" + "=" * 48 + "\n", 1)
        if len(subparts) == 2:
            fp, code = subparts[0].strip(), subparts[1].strip()
            if not fp or not code:
                continue
            if _should_skip_file(fp):
                continue
            raw_files.append((fp, code))

    # Sort by priority (core files first), then cap at _MAX_EMBED_FILES
    raw_files.sort(key=lambda x: _file_priority(x[0]))
    files = raw_files[:_MAX_EMBED_FILES]

    logger.info(
        f"File filter: {len(parts)} raw parts → {len(raw_files)} after filtering "
        f"→ {len(files)} after cap (max {_MAX_EMBED_FILES})"
    )
    return files


def _rich_metadata(file_path: str, source: str) -> dict:
    """Build a rich metadata dict for a single file."""
    symbols = extract_symbols(source)
    imports = extract_imports(source)
    role    = classify_file_role(file_path, source)
    return {
        "file_path":  file_path,
        "role":       role,
        "functions":  json.dumps(symbols["functions"]),
        "classes":    json.dumps(symbols["classes"]),
        "imports":    json.dumps(imports),
        "line_count": str(source.count("\n") + 1),
        "priority":   str(_file_priority(file_path)),
    }

def _make_splitter(source_len: int) -> SentenceSplitter:
    """
    Choose chunk size based on file size so large files don't flood the index
    with redundant chunks while small files are kept whole.
    """
    if source_len > _LARGE_FILE_THRESHOLD:
        return SentenceSplitter(chunk_size=512, chunk_overlap=64)
    return SentenceSplitter(chunk_size=1024, chunk_overlap=128)

def build_query_engine(content: str, repo_name: str) -> dict:
    """
    Build (or reload) a persistent vector index for *repo_name*.

    Returns a dict with keys:
        ``vector_index``   – LlamaIndex VectorStoreIndex
        ``bm25``           – BM25Okapi instance
        ``bm25_nodes``     – list of dicts (for BM25 lookup)
        ``sources``        – Dict[file_path, source_code]
        ``file_priorities``– Dict[file_path, int] for reranking
    """
    repo_hash = hashlib.md5(repo_name.encode()).hexdigest()[:8]
    safe_name = f"{repo_name}_{repo_hash}"

    collection      = _chroma_client.get_or_create_collection(safe_name)
    vector_store    = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    t0    = time.perf_counter()
    files = _split_repo_content(content)
    sources          = {fp: src for fp, src in files}
    file_priorities  = {fp: _file_priority(fp) for fp, _ in files}

    if collection.count() > 0:
        logger.info(
            f"Reusing Chroma collection '{safe_name}' "
            f"({collection.count()} chunks) — skipping embedding."
        )
        index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )
    else:
        logger.info(f"Building '{safe_name}' — embedding {len(files)} files…")
        docs = []
        for fp, src in files:
            meta = _rich_metadata(fp, src)
            docs.append(Document(
                text=src,
                metadata=meta,
                excluded_embed_metadata_keys=["functions", "classes", "imports", "priority"],
                excluded_llm_metadata_keys=["functions", "classes", "imports", "priority"],
            ))

        # Adaptive chunking: group docs by size so large files use smaller chunks
        small_docs = [d for d in docs if len(d.text) <= _LARGE_FILE_THRESHOLD]
        large_docs = [d for d in docs if len(d.text) > _LARGE_FILE_THRESHOLD]

        all_nodes = []
        if small_docs:
            small_splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=128)
            all_nodes.extend(small_splitter.get_nodes_from_documents(small_docs))
        if large_docs:
            large_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=64)
            all_nodes.extend(large_splitter.get_nodes_from_documents(large_docs))

        index = VectorStoreIndex(
            nodes=all_nodes,
            storage_context=storage_context,
            show_progress=True,
        )
        logger.info(
            f"Index built in {time.perf_counter() - t0:.1f}s — "
            f"{len(all_nodes)} chunks from {len(files)} files."
        )

    # BM25 — built over whole-file text (not chunks) for file-level matching
    bm25_corpus, bm25_nodes = [], []
    for fp, src in files:
        tokens = re.findall(r"[a-zA-Z_]\w*", src)
        bm25_corpus.append(tokens)
        # Store only first 4 000 chars to keep memory reasonable
        bm25_nodes.append({"file_path": fp, "text": src[:4_000]})

    bm25 = BM25Okapi(bm25_corpus) if bm25_corpus else None

    return {
        "vector_index":    index,
        "bm25":            bm25,
        "bm25_nodes":      bm25_nodes,
        "sources":         sources,
        "file_priorities": file_priorities,
    }

def extract_json(text: str) -> dict:
    """Safely extract the first JSON object from an LLM response."""
    if not text:
        return {}

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start == -1:
        logger.warning("extract_json: no '{' found in LLM output")
        return {}

    depth, end, in_string, escape = 0, -1, False, False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        open_braces = text.count("{", start) - text.count("}", start)
        candidate   = text[start:] + ("}" * max(open_braces, 1))
        logger.warning("extract_json: JSON appears truncated; attempting repair")
    else:
        candidate = text[start : end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning(f"extract_json: decode error: {exc}")
        return {}

def run_issue_analyzer(tree: str, issue_full: str) -> dict:
    """Categorise the issue: type, difficulty, required skills, affected areas."""
    # Trim tree more aggressively — the analyzer only needs structural context
    prompt = f"""You are an expert open-source contributor mentor. Analyse the GitHub issue and return ONLY valid JSON (no markdown fences, no extra text).

Repository structure (truncated):
{tree[:2000]}

Issue:
{issue_full[:1500]}

Return a JSON object with exactly these keys:
{{
  "issue_type": "bug|feature|docs|refactor|test",
  "difficulty": "beginner|intermediate|advanced",
  "difficulty_reason": "one short sentence",
  "root_cause_hypothesis": "what is most likely causing this",
  "required_skills": ["skill1", "skill2"],
  "estimated_hours": "1-2|2-4|4-8|8-16|16+",
  "affected_areas": ["area1", "area2"],
  "good_first_issue": true
}}"""
    try:
        resp = Settings.llm.complete(prompt)
        return extract_json(str(resp))
    except Exception as exc:
        logger.warning(f"Issue analysis failed: {exc}")
        return {}

def run_retrieval_agent(engine_bundle: dict, issue_full: str) -> dict:
    """
    Hybrid retrieval → issue-aware reranking pipeline.

    Stage 1 — Recall:  cast a wide net with both semantic (top-12) and BM25
                        (top-12, threshold lowered to 0.5 so more candidates
                        reach the reranker rather than being lost early).
    Stage 2 — Rerank:  ``reranker.rerank()`` scores candidates on five
                        independent signals (symbol match, filepath domain,
                        dependency proximity, retrieval agreement, penalty)
                        and partitions results into HIGH/MEDIUM/LOW/PENALISED
                        confidence tiers.
    Stage 3 — Return:  only non-PENALISED files are surfaced (up to 6).
                        The reranker's ``RerankerResult`` metadata is threaded
                        through so the reasoning agent can see confidence tiers.
    """
    vector_index:    VectorStoreIndex    = engine_bundle["vector_index"]
    bm25:            Optional[BM25Okapi] = engine_bundle["bm25"]
    bm25_nodes:      list                = engine_bundle["bm25_nodes"]
    sources:         Dict[str, str]      = engine_bundle["sources"]

    candidates: Dict[str, Tuple[float, str]] = {}

    # --- Stage 1a: Semantic retrieval (wider net for reranker) ---
    try:
        retriever = vector_index.as_retriever(similarity_top_k=25)
        nodes: List[NodeWithScore] = retriever.retrieve(issue_full)
        for node in nodes:
            fp    = node.metadata.get("file_path", "")
            score = node.score or 0.0
            if fp and (fp not in candidates or score > candidates[fp][0]):
                candidates[fp] = (score, "semantic")
    except Exception as exc:
        logger.warning(f"Vector retrieval failed: {exc}")

    # --- Stage 1b: BM25 retrieval ---
    if bm25 and bm25_nodes:
        query_tokens = re.findall(r"[a-zA-Z_]\w*", issue_full)
        bm25_scores  = bm25.get_scores(query_tokens)
        top_k        = min(12, len(bm25_scores))
        top_indices  = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[:top_k]
        for idx in top_indices:
            score = float(bm25_scores[idx])
            if score < 0.5:
                continue
            fp = bm25_nodes[idx]["file_path"]
            if fp not in candidates:
                candidates[fp] = (score, "bm25")

    if not candidates:
        return {"relevant_files": [], "key_functions": [], "search_keywords": [],
                "reranker": None}

    # --- Stage 2: Issue-aware reranking ---
    reranker_result = rerank(
        candidates  = candidates,
        sources     = sources,
        issue_full  = issue_full,
        top_k       = 6,
    )

    if reranker_result.low_confidence:
      logger.warning(
        "Low-confidence retrieval detected — using fallback semantic ranking"
      )

      fallback_candidates = sorted(
        candidates.items(),
        key=lambda x: x[1][0],
        reverse=True,
      )[:6]

      relevant_files = []

      for fp, (score, method) in fallback_candidates:
        relevant_files.append({
          "path": fp,
          "relevance": "medium",
          "score": score,
          "method": method,
          "reason": "Fallback semantic retrieval",
          "functions": [],
          "classes": [],
          "role": "unknown",
          "signals": {
            "symbol": 0,
            "filepath": 0,
            "dep": 0,
            "agreement": 0,
            "penalty": 0,
          },
          "matched_symbols": [],
        })

      return {
        "relevant_files": relevant_files,
        "key_functions": [],
        "search_keywords": [],
        "most_likely_fix_zone": None,
        "reranker": {
          "confidence_tier": "LOW",
          "overall_confidence": 0.0,
          "anchor_file": None,
          "low_confidence": True,
          "explanation": "Fallback semantic retrieval used",
        },
      }

    logger.info(
        f"Reranker: {len(candidates)} candidates → "
        f"{len(reranker_result.ranked_files)} after reranking | "
        f"top_tier={reranker_result.confidence_tier} | "
        f"anchor={reranker_result.anchor_file} | "
        f"low_conf={reranker_result.low_confidence}"
    )

    # --- Stage 3: Build the response payload ---
    relevant_files = []
    for r in reranker_result.ranked_files:
        relevant_files.append({
            "path":             r.path,
            "relevance":        r.confidence_tier.lower(),   # high/medium/low
            "score":            r.composite_score,
            "retrieval_score":  round(r.retrieval_score, 3),
            "method":           r.retrieval_method,
            "reason":           r.reason,
            "functions":        r.functions,
            "classes":          r.classes,
            "role":             r.role,
            "signals": {
                "symbol":    r.symbol_score,
                "filepath":  r.filepath_score,
                "dep":       r.dep_score,
                "agreement": r.agreement_score,
                "penalty":   r.penalty,
            },
            "matched_symbols": r.matched_symbols,
        })

    fix_zone = None
    if relevant_files:
        top = relevant_files[0]
        fix_zone = {
            "file_path":            top.get("path"),
            "role":                 top.get("role"),
            "localisation_tier":    reranker_result.confidence_tier,
            "localisation_score":   round(reranker_result.overall_confidence, 3),
            "matched_symbols":      top.get("matched_symbols", [])[:8],
            "likely_functions":     (top.get("functions") or [])[:8],
            "likely_classes":       (top.get("classes") or [])[:8],
            "reason":               top.get("reason"),
        }

    entities = extract_issue_entities(issue_full)
    keywords = []
    seen = set()
    for e in entities:
        if e.kind in ("symbol", "error_type", "module") and e.confidence >= 0.55:
            if e.text not in seen:
                keywords.append(e.text)
                seen.add(e.text)
        if len(keywords) >= 10:
            break

    return {
        "relevant_files":  relevant_files,
        "key_functions":   list({fn for f in relevant_files for fn in f["functions"]})[:10],
        "search_keywords": keywords,
        "most_likely_fix_zone": fix_zone,
        # Reranker metadata surfaced to API consumers and the reasoning agent
        "reranker": {
            "confidence_tier":    reranker_result.confidence_tier,
            "overall_confidence": round(reranker_result.overall_confidence, 3),
            "anchor_file":        reranker_result.anchor_file,
            "low_confidence":     reranker_result.low_confidence,
            "explanation":        reranker_result.explanation,
        },
    }

def _build_code_context(
    retrieved_files: List[str],
    sources: Dict[str, str],
    max_chars_per_file: int = 2500,
    total_cap: int = 10_000,
) -> str:
    """
    Assemble a tight code context block.

    Enforces both a per-file cap and a total character cap so the reasoning
    prompt never balloons regardless of how many files are retrieved.
    """
    parts: List[str] = []
    total = 0
    for fp in retrieved_files:
        src = sources.get(fp, "")
        if not src:
            continue
        snippet = src[:max_chars_per_file]
        if total + len(snippet) > total_cap:
            remaining = total_cap - total
            if remaining < 200:          # not worth adding a tiny snippet
                break
            snippet = snippet[:remaining]
        parts.append(f"--- File: {fp} ---\n{snippet}")
        total += len(snippet)
        if total >= total_cap:
            break
    return "\n\n".join(parts)

def _build_code_context_with_decay(
    core_files: List[str],
    supporting_files: List[str],
    sources: Dict[str, str],
    *,
    core_max_chars: int = 2200,
    supporting_max_chars: int = 700,
    total_cap: int = 8_000,
) -> str:
    """
    Build a context block that enforces *importance decay*.

    - Core files dominate the prompt (larger snippets).
    - Supporting files are included as lightweight breadcrumbs only.
    """
    parts: List[str] = []
    total = 0

    def _add(fp: str, cap: int, label: str) -> None:
        nonlocal total
        src = sources.get(fp, "")
        if not src:
            return
        snippet = src[:cap]
        if total + len(snippet) > total_cap:
            remaining = total_cap - total
            if remaining < 200:
                return
            snippet = snippet[:remaining]
        parts.append(f"--- {label}: {fp} ---\n{snippet}")
        total += len(snippet)

    for fp in core_files:
        _add(fp, core_max_chars, "CORE FILE")
        if total >= total_cap:
            break

    if total < total_cap and supporting_files:
        parts.append("--- SUPPORTING FILES (low importance; use only if directly tied to issue entities) ---")
        for fp in supporting_files:
            _add(fp, supporting_max_chars, "SUPPORTING FILE")
            if total >= total_cap:
                break

    return "\n\n".join(parts)

def _extract_first_path_token(text: str) -> str:
    """Extract a likely file path token from the start of a string."""
    if not text:
        return ""
    # Handles: "(path/file.py) ...", "path/file.py — ...", "path/file.py → ..."
    t = text.strip().lstrip("(")
    return re.split(r"[\s)→:,—–-]", t, maxsplit=1)[0].strip()

def _filter_list_of_strings_by_paths(items: list, valid_path_set: set) -> list:
    """Drop items that reference a non-retrieved file path token."""
    if not isinstance(items, list):
        return items
    cleaned = []
    for it in items:
        if not isinstance(it, str):
            cleaned.append(it)
            continue
        p = _extract_first_path_token(it)
        if not p or p in valid_path_set:
            cleaned.append(it)
        else:
            logger.warning(f"Stripped hallucinated path from list item: {p!r}")
    return cleaned

def find_model_related_files(sources: Dict[str, str]) -> List[dict]:
  """
  Find files most likely related to ML/deepfake model loading,
  inference, prediction, or weight initialization.
  """

  scored_files = []

  for fp, src in sources.items():
    src_lower = src.lower()

    score = 0
    matched_keywords = []

    for kw in MODEL_KEYWORDS:
      if kw.lower() in src_lower:
        score += 1
        matched_keywords.append(kw)

    # Boost backend/python inference files
    if fp.endswith(".py"):
      score += 2

    if any(x in fp.lower() for x in [
      "model",
      "infer",
      "predict",
      "detect",
      "service",
      "backend",
      "classifier",
    ]):
      score += 3

    if score > 0:
      scored_files.append({
        "path": fp,
        "score": score,
        "matched_keywords": matched_keywords[:10],
      })

  scored_files.sort(key=lambda x: x["score"], reverse=True)

  return scored_files[:10]

def _generate_patch(
    retrieved_files: List[str],
    sources: Dict[str, str],
    issue_full: str,
) -> Optional[dict]:
    """Ask the LLM to produce a unified diff for the most relevant file."""
    if not retrieved_files:
        return None

    primary_file = retrieved_files[0]
    original     = sources.get(primary_file, "")
    if not original:
        return None

    prompt = f"""You are a senior engineer. Given the issue and the file below, produce a minimal unified diff (--- a/file  +++ b/file format) that fixes or implements the issue.
Output ONLY the diff, no explanation, no markdown fences.

Issue:
{issue_full[:500]}

File ({primary_file}):
{original[:2500]}"""
    try:
        diff_text = str(Settings.llm.complete(prompt)).strip()
        if diff_text.startswith(("---", "@@", "diff")):
            return {"file_path": primary_file, "diff": diff_text}
    except Exception as exc:
        logger.warning(f"Patch generation failed: {exc}")
    return None

def _build_grounding_preamble(
    valid_paths: List[str],
    low_confidence: bool,
    confidence_tier: str,
    reranker_explanation: str,
) -> str:
    """
    Build the grounding preamble that is prepended to every reasoning prompt.

    When confidence is LOW or PENALISED the preamble is expanded with an
    explicit uncertainty directive so the model admits rather than invents.
    """
    path_list = "\n".join(f"  - {p}" for p in valid_paths) or "  (none)"

    base = (
        "═══════════════════════════════════════════════════════\n"
        "GROUNDING CONTRACT — READ BEFORE GENERATING ANY OUTPUT\n"
        "═══════════════════════════════════════════════════════\n"
        "You are an expert open-source mentor. You MUST follow every rule below.\n\n"
        "RULE 1 — FILE SCOPE\n"
        f"  You may ONLY reference files from this exact list:\n{path_list}\n"
        "  Any file_path value in your JSON that is NOT in this list is a hallucination.\n\n"
        "RULE 2 — NO INVENTION\n"
        "  Do NOT invent function names, class names, variable names, or documentation links.\n"
        "  Every symbol you mention must appear verbatim in the source code provided.\n\n"
        "RULE 3 — UNCERTAINTY\n"
        "  If the code context is insufficient to answer with confidence, say so explicitly.\n"
        "  Use phrases like 'Based on available context…' or 'This cannot be determined from the retrieved files.'\n\n"
        "RULE 4 — NO SPECULATION\n"
        "  Do NOT suggest files that are not in the list above, even if you think they might exist.\n"
        "  Do NOT reference README, CONTRIBUTING, or documentation files unless they appear in the list.\n\n"
    )

    confidence_block = (
        f"LOCALISATION CONFIDENCE: {confidence_tier}\n"
        f"RERANKER ASSESSMENT: {reranker_explanation}\n\n"
    )

    if low_confidence:
        uncertainty_directive = (
            "⚠ LOW-CONFIDENCE WARNING ⚠\n"
            "The bug localisation system has LOW confidence that the retrieved files\n"
            "are the correct fix location. You MUST:\n"
            "  • Begin your 'explanation' field with: 'Note: localisation confidence is low.'\n"
            "  • State in 'common_mistakes' that the fix location may differ from retrieved files.\n"
            "  • Do NOT produce a confident step-by-step patch if evidence is insufficient.\n"
            "  • Set 'where_to_start' to the most likely candidate but flag uncertainty.\n\n"
        )
        return base + confidence_block + uncertainty_directive
    else:
        return base + confidence_block

def run_reasoning_agent(
    tree: str,
    retrieved_files: List[str],
    sources: Dict[str, str],
    issue_full: str,
    include_patch: bool = False,
    reranker_meta: Optional[dict] = None,
) -> dict:
    """
    Confidence-aware mentorship reasoning agent.

    New behaviour vs. previous version:
    - Grounding preamble is dynamically constructed from reranker confidence
    - LOW/PENALISED confidence triggers explicit uncertainty directives in prompt
    - The reranker's explanation and anchor file are injected into the prompt
    - File-path validation: any path invented by the LLM that isn't in the
      retrieved set is stripped from the output before returning
    - dep_chain is always computed statically and injected — never LLM-generated
    """
    reranker_meta    = reranker_meta or {}
    low_confidence   = reranker_meta.get("low_confidence", False)
    confidence_tier  = reranker_meta.get("confidence_tier", "UNKNOWN")
    reranker_explain = reranker_meta.get("explanation", "No reranker metadata available.")
    anchor_file      = reranker_meta.get("anchor_file")
    overall_score    = reranker_meta.get("overall_confidence")

    # Use a core/supporting split with context-importance decay.
    # Anchor file is always treated as the highest-importance core file.
    ordered = list(dict.fromkeys(
        ([anchor_file] if anchor_file and anchor_file in retrieved_files else []) +
        [f for f in retrieved_files if f != anchor_file]
    ))
    core_files       = ordered[:2]
    supporting_files = ordered[2:6]
    code_context = _build_code_context_with_decay(
        core_files=core_files,
        supporting_files=supporting_files,
        sources=sources,
        core_max_chars=2200,
        supporting_max_chars=650,
        total_cap=8_000,
    )

    # Static dependency chain — never LLM-generated
    dep_chain: List[str] = []
    # Only expand dependencies from core files; supporting files should never
    # dominate reasoning unless retrieval signals are strong enough to elevate them.
    for fp in core_files[:2]:
        dep_chain.extend(build_dependency_chain(fp, sources))
    dep_chain = list(dict.fromkeys(dep_chain))[:12]

    # File roles
    file_role_lines: List[str] = []
    for fp in retrieved_files:
        src  = sources.get(fp, "")
        role = classify_file_role(fp, src)
        file_role_lines.append(f"  - {fp}  [{role}]")
    file_role_str = "\n".join(file_role_lines) or "  (none)"

    # Anchor hint for the model
    anchor_hint = (
        f"ANCHOR FILE (highest symbol-match confidence): {anchor_file}\n"
        if anchor_file else ""
    )

    grounding_preamble = _build_grounding_preamble(
        valid_paths          = retrieved_files,
        low_confidence       = low_confidence,
        confidence_tier      = confidence_tier,
        reranker_explanation = reranker_explain,
    )

    uncertainty_note = (
        '"Note: localisation confidence is low — fix location may differ from retrieved files."'
        if low_confidence else
        '"Based on the retrieved source code…"'
    )

    # Issue-centric focus entities — constrain the model to stay on-domain.
    issue_entities = extract_issue_entities(issue_full)
    focus_symbols  = [e.text for e in issue_entities if e.kind in ("symbol", "error_type") and e.confidence >= 0.60][:12]
    focus_paths    = [e.text for e in issue_entities if e.kind == "filepath" and e.confidence >= 0.70][:8]
    focus_modules  = [e.text for e in issue_entities if e.kind == "module" and e.confidence >= 0.70][:8]
    focus_block = (
        "ISSUE-FOCUS ENTITIES (highest precision; prioritize these):\n"
        f"  - symbols/errors: {', '.join(focus_symbols) if focus_symbols else '(none)'}\n"
        f"  - filepaths:      {', '.join(focus_paths) if focus_paths else '(none)'}\n"
        f"  - modules:        {', '.join(focus_modules) if focus_modules else '(none)'}\n"
    )

    prompt = f"""{grounding_preamble}
You are a patient, expert open-source mentor helping a BEGINNER make their first contribution.
Produce a structured contribution guide that is STRICTLY ISSUE-CENTRIC:
- Focus ONLY on runtime paths, middleware flows, configuration flows, and symbols directly referenced by the issue.
- Treat supporting/infrastructure/utility modules as LOW importance unless they contain a focused entity above.
- Do NOT provide broad repository explanations. Every sentence must connect to a focused entity or the anchor file.

{anchor_hint}File roles:
{file_role_str}

Core files (highest importance): {", ".join(core_files) if core_files else "(none)"}
Supporting files (low importance): {", ".join(supporting_files) if supporting_files else "(none)"}

{focus_block}

Issue:
{issue_full[:800]}

Relevant source code (ONLY reference symbols that appear in the code below):
{code_context}

Dependency chain (statically computed — do not modify):
{chr(10).join(dep_chain) if dep_chain else "N/A"}

Return ONLY valid JSON — no markdown fences, no commentary outside the JSON object.
Start your "explanation" with exactly: {uncertainty_note}

{{
  "where_to_start": "<file path from valid list + function name found in that file's source>",
  "what_to_read_first": [
    "<file_path — specific thing to look for in that file>",
    "<file_path — specific thing to look for in that file>"
  ],
  "explanation": "<begin with the uncertainty_note above, then 2-4 sentences grounded in the code>",
  "logic_trace": [
    "Step 1: (exact_file.py) <what this file does relative to the issue>",
    "Step 2: (exact_file.py) <what happens next>"
  ],
  "contribution_path": [
    {{
      "step": 1,
      "title": "<imperative verb phrase>",
      "description": "<concrete instruction — cite only symbols visible in the source above>",
      "files_involved": ["<path from valid list only>"]
    }}
  ],
  "common_mistakes": [
    "<concrete pitfall drawn from the actual code>",
    "<second pitfall or uncertainty warning if confidence is low>"
  ],
  "dependency_chain": {json.dumps(dep_chain)},
  "confidence_note": "<one sentence summarising how confident the localisation is and why>"
}}"""

    # Valid path set for post-processing validation
    valid_path_set: set = set(retrieved_files)

    def _sanitise(result: dict) -> dict:
        """
        Strip any file paths the LLM invented that aren't in the retrieved set.
        Mutates and returns the result dict.
        """
        # where_to_start: extract path prefix and validate
        wts = result.get("where_to_start", "")
        if wts:
            # The model may write "path/file.py → function_name()" — take the path part
            wts_path = re.split(r"[\s→:,]", wts)[0].strip()
            if wts_path and wts_path not in valid_path_set:
                logger.warning(f"Reasoning agent hallucinated where_to_start path: {wts_path!r}")
                result["where_to_start"] = retrieved_files[0] if retrieved_files else ""

        # what_to_read_first: filter out invented paths
        wtrf = result.get("what_to_read_first", [])
        if isinstance(wtrf, list):
            cleaned = []
            for item in wtrf:
                # Item format: "path/file.py — description"
                path_part = re.split(r"[\s—–-]", item)[0].strip()
                if path_part in valid_path_set or path_part not in sources:
                    cleaned.append(item)
                else:
                    logger.warning(f"Stripped hallucinated path from what_to_read_first: {path_part!r}")
            result["what_to_read_first"] = cleaned

        # logic_trace: drop steps that reference non-retrieved files
        result["logic_trace"] = _filter_list_of_strings_by_paths(
            result.get("logic_trace", []),
            valid_path_set,
        )

        # contribution_path: validate files_involved
        for step in result.get("contribution_path", []):
            fi = step.get("files_involved", [])
            if isinstance(fi, list):
                step["files_involved"] = [
                    f for f in fi if f in valid_path_set
                ]

        return result

    try:
        resp   = str(Settings.llm.complete(prompt, format="json"))
        result = extract_json(resp)

        if not result:
            logger.warning("Reasoning agent: no valid JSON; using structured fallback.")
            result = _low_confidence_fallback(retrieved_files, dep_chain, low_confidence)
        else:
            result = _sanitise(result)
            # Always inject static dep_chain (model must not modify it)
            result["dependency_chain"] = dep_chain
            # Inject reranker metadata
            result["localisation_confidence"] = {
                "tier":          confidence_tier,
                "score":         overall_score,
                "anchor_file":   anchor_file,
                "low_confidence": low_confidence,
            }

            # Always expose a tight "fix zone" so callers can act without
            # reading the entire narrative.
            result["most_likely_fix_zone"] = {
                "file_path":          core_files[0] if core_files else (retrieved_files[0] if retrieved_files else ""),
                "localisation_tier":  confidence_tier,
                "localisation_score": overall_score,
                "anchor_file":        anchor_file,
                "focus_symbols":      focus_symbols,
            }

            # Hard-abstain guardrail: if retrieval is low-confidence, force the
            # response to stay in "mentor mode" (no strong claims) by ensuring
            # the model includes an explicit uncertainty note.
            if low_confidence:
                expl = str(result.get("explanation", "") or "")
                if "localisation confidence is low" not in expl.lower():
                    result["explanation"] = (
                        "Note: localisation confidence is low — fix location may differ from retrieved files. "
                        + expl
                    ).strip()

    except Exception as exc:
        logger.error(f"Reasoning agent error: {exc}")
        result = {
            "explanation":             f"Failed to generate guide: {exc}",
            "where_to_start":          retrieved_files[0] if retrieved_files else "",
            "what_to_read_first":      retrieved_files[:2],
            "logic_trace":             ["Error during reasoning — review retrieval results manually."],
            "contribution_path":       [],
            "common_mistakes":         ["An internal error occurred. Verify the repository was indexed correctly."],
            "dependency_chain":        dep_chain,
            "confidence_note":         "Reasoning failed; confidence cannot be assessed.",
            "localisation_confidence": reranker_meta,
        }

    # If localisation confidence is low, do not return an auto patch by default.
    # (Even when include_patch=True, this protects production usage from
    # generating misleading diffs against the wrong file.)
    if include_patch:
        if not low_confidence:
            result["suggested_patch"] = _generate_patch(retrieved_files, sources, issue_full)
        else:
            result["suggested_patch"] = None

    return result

def _low_confidence_fallback(
    retrieved_files: List[str],
    dep_chain: List[str],
    low_confidence: bool,
) -> dict:
    """Structured fallback when the LLM fails to produce valid JSON."""
    uncertainty = (
        "Note: localisation confidence is low — fix location may differ from retrieved files. "
        if low_confidence else ""
    )
    return {
        "where_to_start":     retrieved_files[0] if retrieved_files else "",
        "what_to_read_first": retrieved_files[:2],
        "explanation": (
            f"{uncertainty}The AI retrieved relevant files but could not format a structured guide. "
            "Review the files in the retrieval section to begin your investigation."
        ),
        "logic_trace":       ["Manual review required — see retrieved files above."],
        "contribution_path": [{
            "step": 1,
            "title": "Review retrieved files",
            "description": (
                "Open each file listed in the retrieval section and search for the "
                "symbols mentioned in the issue (class/function names). Start with the "
                "highest-confidence file."
            ),
            "files_involved": retrieved_files[:3],
        }],
        "common_mistakes": [
            "Do not modify files not listed in the retrieval results.",
            "Verify the fix location manually before writing code — confidence is low."
            if low_confidence else
            "Ensure you understand the dependency chain before modifying files.",
        ],
        "dependency_chain":        dep_chain,
        "confidence_note":         "Fallback response — LLM formatting error.",
        "localisation_confidence": None,
    }

def run_repo_qa(engine_bundle: dict, question: str) -> dict:
    """
    Answer a free-form question about the repository using the RAG pipeline.

    Grounding: instructs the model to cite only retrieved files and flag gaps.
    """
    sources: Dict[str, str] = engine_bundle["sources"]
    question_lower = question.lower()

    # ---------------------------------------------------------
    # Architecture Query Mode
    # ---------------------------------------------------------

    is_architecture_query = any(
      q in question_lower
      for q in ARCHITECTURE_QUERIES
    )

    if is_architecture_query:
      logger.info("Architecture query detected — using structure-aware retrieval")

      model_files = find_model_related_files(sources)

      if not model_files:
        return {
          "answer": (
            "I could not confidently identify the model loading files."
          ),
          "relevant_files": [],
        }

      top_files = model_files[:5]

      formatted_files = "\n".join([
        f"- {f['path']} (matched: {', '.join(f['matched_keywords'][:5])})"
        for f in top_files
      ])

      answer = (
        "These files are most likely responsible for loading or running "
        "the deepfake detection model:\n\n"
        f"{formatted_files}\n\n"
        "Look for code involving model initialization, weight loading, "
        "or prediction/inference logic."
      )

      return {
        "answer": answer,
        "relevant_files": [f["path"] for f in top_files],
      }

    retrieval       = run_retrieval_agent(engine_bundle, question)
    retrieved_files = [f["path"] for f in retrieval.get("relevant_files", [])]
    sources: Dict[str, str] = engine_bundle["sources"]

    # Tighter context than before (2 000 per file, 6 000 total)
    code_context = _build_code_context(retrieved_files, sources, max_chars_per_file=2_000, total_cap=6_000)
    valid_paths  = "\n".join(f"  - {fp}" for fp in retrieved_files) or "  (none)"

    prompt = f"""You are an expert AI mentor helping a developer understand a codebase.
Answer the question using ONLY the source code provided. Do not reference files not listed below.
If the answer cannot be found in the context, say so clearly.

Files you may reference:
{valid_paths}

Question: {question[:600]}

Relevant source code:
{code_context}

Format your answer in clean Markdown. Cite specific function or class names from the code when possible."""
    try:
        answer = str(Settings.llm.complete(prompt)).strip()
    except Exception as exc:
        logger.exception("QA agent failed")

        return {
          "answer": (
            "The QA agent failed to generate a grounded response. "
            "Please check the inference server or Ollama connection."
          ),
          "relevant_files": [],
          "error": str(exc),
        }

    return {
        "answer":         answer,
        "relevant_files": retrieved_files,
    }

async def build_query_engine_async(content: str, repo_name: str) -> dict:
    """
    Run build_query_engine in a thread pool so the FastAPI event loop stays
    responsive during the CPU/GPU-heavy embedding phase.
    """
    return await asyncio.to_thread(build_query_engine, content, repo_name)