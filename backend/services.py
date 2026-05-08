from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import torch
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from llama_index.llms.ollama import Ollama
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

Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-base-en-v1.5",
    device=device,
    embed_batch_size=32,          # halved to reduce VRAM spikes
)

Settings.llm = Ollama(
    model="qwen2.5-coder:1.5b",
    base_url="http://localhost:11434",
    request_timeout=300.0,        # tightened from 600 s
    context_window=16384,         # halved: forces tighter prompts, faster inference
)

# ---------------------------------------------------------------------------
# Constants — tunable in one place
# ---------------------------------------------------------------------------

# Directories that are almost never needed for contribution guidance
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

# File extensions that carry no indexable logic
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

# Hard limit: never embed more than this many files per repo
_MAX_EMBED_FILES = 300
# Hard limit: files larger than this char count are chunked more aggressively
_LARGE_FILE_THRESHOLD = 8_000


# ---------------------------------------------------------------------------
# Intelligent file filtering
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Smarter chunking: adaptive chunk size by file size
# ---------------------------------------------------------------------------

def _make_splitter(source_len: int) -> SentenceSplitter:
    """
    Choose chunk size based on file size so large files don't flood the index
    with redundant chunks while small files are kept whole.
    """
    if source_len > _LARGE_FILE_THRESHOLD:
        return SentenceSplitter(chunk_size=512, chunk_overlap=64)
    return SentenceSplitter(chunk_size=1024, chunk_overlap=128)


# ---------------------------------------------------------------------------
# Index build
# ---------------------------------------------------------------------------

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
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_name)[:60] or "repo"

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


# ---------------------------------------------------------------------------
# JSON extraction (unchanged — already solid)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Issue Analyzer
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def _template_reason(file_path: str, method: str, score: Optional[float]) -> str:
    """Fast, zero-LLM-call fallback reason string."""
    score_str = f"{score:.2f}" if score is not None else "n/a"
    return f"{method.capitalize()} match (score {score_str}) in {file_path}."


def _rerank_files(
    seen: Dict[str, Tuple[float, str]],
    file_priorities: Dict[str, int],
    top_k: int = 8,
) -> List[Tuple[str, float, str]]:
    """
    Rerank retrieved files by combining retrieval score with structural priority.

    Priority 0 (core source) files receive a +0.3 score bonus; priority 1 files
    receive +0.15; others receive no bonus.  Files are then sorted descending by
    adjusted score.
    """
    bonus = {0: 0.30, 1: 0.15, 2: 0.05}
    ranked = []
    for fp, (score, method) in seen.items():
        p = file_priorities.get(fp, 3)
        adjusted = score + bonus.get(p, 0.0)
        ranked.append((fp, adjusted, method))
    ranked.sort(key=lambda x: -x[1])
    return ranked[:top_k]


def run_retrieval_agent(engine_bundle: dict, issue_full: str) -> dict:
    """
    Hybrid retrieval: combine vector similarity with BM25, then rerank.

    Key changes vs. original:
    - _explain_why LLM calls eliminated for every file (replaced by fast template)
    - Structural priority reranking applied after score fusion
    - BM25 threshold raised from 0.5 → 1.0 to reduce noise
    - Result cap lowered from 8 → 6 to keep reasoning prompt tight
    """
    vector_index:    VectorStoreIndex  = engine_bundle["vector_index"]
    bm25:            Optional[BM25Okapi] = engine_bundle["bm25"]
    bm25_nodes:      list              = engine_bundle["bm25_nodes"]
    sources:         Dict[str, str]    = engine_bundle["sources"]
    file_priorities: Dict[str, int]    = engine_bundle.get("file_priorities", {})

    seen: Dict[str, Tuple[float, str]] = {}

    # --- Semantic retrieval ---
    try:
        retriever = vector_index.as_retriever(similarity_top_k=8)
        nodes: List[NodeWithScore] = retriever.retrieve(issue_full)
        for node in nodes:
            fp    = node.metadata.get("file_path", "")
            score = node.score or 0.0
            if fp and (fp not in seen or score > seen[fp][0]):
                seen[fp] = (score, "semantic")
    except Exception as exc:
        logger.warning(f"Vector retrieval failed: {exc}")

    # --- BM25 retrieval ---
    if bm25 and bm25_nodes:
        query_tokens = re.findall(r"[a-zA-Z_]\w*", issue_full)
        bm25_scores  = bm25.get_scores(query_tokens)
        top_k        = min(8, len(bm25_scores))
        top_indices  = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[:top_k]
        for idx in top_indices:
            score = float(bm25_scores[idx])
            if score < 1.0:             # raised threshold (was 0.5)
                continue
            fp = bm25_nodes[idx]["file_path"]
            if fp not in seen or (score > seen[fp][0] and seen[fp][1] == "semantic"):
                seen[fp] = (score, "bm25")

    # --- Rerank ---
    ranked = _rerank_files(seen, file_priorities, top_k=6)

    relevant_files = []
    for fp, adj_score, method in ranked:
        src     = sources.get(fp, "")
        symbols = extract_symbols(src)
        role    = classify_file_role(fp, src)
        # Fast template reason — no extra LLM call per file
        reason  = _template_reason(fp, method, adj_score)
        relevant_files.append({
            "path":      fp,
            "relevance": "high" if adj_score >= 1.0 else "medium",
            "score":     round(adj_score, 3),
            "method":    method,
            "reason":    reason,
            "functions": symbols["functions"],
            "classes":   symbols["classes"],
            "role":      role,
        })

    # Extract keywords for UI display
    keyword_text = re.sub(r"^Title:[^\n]*\n", "", issue_full, flags=re.IGNORECASE).strip()
    _STOPWORDS = {
        "this", "that", "with", "from", "have", "will", "when", "what",
        "which", "there", "their", "about", "would", "could", "should",
    }
    raw_keywords = re.findall(r"[A-Z][a-z]+(?:[A-Z][a-z]*)+|[a-z_]{4,}", keyword_text)
    keywords = [kw for kw in dict.fromkeys(raw_keywords) if kw not in _STOPWORDS][:10]

    return {
        "relevant_files":  relevant_files,
        "key_functions":   list({fn for f in relevant_files for fn in f["functions"]})[:10],
        "search_keywords": keywords,
    }


# ---------------------------------------------------------------------------
# Code context builder — grounding control
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Reasoning Agent — grounded, trim prompts
# ---------------------------------------------------------------------------

# Explicit grounding instruction prepended to every reasoning prompt
_GROUNDING_PREAMBLE = (
    "IMPORTANT GROUNDING RULES:\n"
    "1. Reference ONLY files listed in 'Relevant source code' below.\n"
    "2. Do NOT invent file paths, function names, or documentation links.\n"
    "3. If you cannot find the answer in the provided context, say so explicitly.\n"
    "4. Every file_path value in your JSON MUST appear in the 'File roles detected' list.\n\n"
)


def run_reasoning_agent(
    tree: str,
    retrieved_files: List[str],
    sources: Dict[str, str],
    issue_full: str,
    include_patch: bool = False,
) -> dict:
    """
    Mentorship-focused reasoning agent with strict grounding controls.

    Changes vs. original:
    - _GROUNDING_PREAMBLE enforces file-path grounding
    - context window trimmed: tree 1 000 chars, code 8 000 total, issue 800 chars
    - Only top 3 files used for dependency tracing (was 3, made explicit)
    - dep_chain injected at JSON-build time, not appended by LLM
    """
    top_files    = retrieved_files[:4]
    code_context = _build_code_context(top_files, sources, max_chars_per_file=2000, total_cap=8_000)

    dep_chain: List[str] = []
    for fp in retrieved_files[:3]:
        dep_chain.extend(build_dependency_chain(fp, sources))
    dep_chain = list(dict.fromkeys(dep_chain))

    file_roles = []
    for fp in retrieved_files:
        src  = sources.get(fp, "")
        role = classify_file_role(fp, src)
        file_roles.append(f"  - {fp}  [{role}]")
    file_role_str  = "\n".join(file_roles) if file_roles else "  (none)"
    valid_paths_str = "\n".join(f"  {fp}" for fp in retrieved_files) or "  (none)"

    prompt = f"""{_GROUNDING_PREAMBLE}You are a patient, expert open-source mentor helping a BEGINNER make their first contribution.
Use ONLY the repository tree, issue, and source code provided below.

Repository tree (truncated):
{tree[:1000]}

Valid file paths you may reference:
{valid_paths_str}

File roles detected:
{file_role_str}

Issue:
{issue_full[:800]}

Relevant source code:
{code_context}

Dependency chain detected:
{chr(10).join(dep_chain[:10]) if dep_chain else "N/A"}

Return ONLY valid JSON with this exact structure (replace all placeholder strings):
{{
  "where_to_start": "<exact file path AND function name to open first — must be in valid paths list>",
  "what_to_read_first": [
    "<file_path_1 — what to look for>",
    "<file_path_2 — what to look for>"
  ],
  "explanation": "<3-5 sentences in plain English describing what the relevant code does>",
  "logic_trace": [
    "Step 1: (file.py) <what happens here>",
    "Step 2: (file.py) <what happens next>"
  ],
  "contribution_path": [
    {{
      "step": 1,
      "title": "<short imperative title>",
      "description": "<detailed beginner-friendly instruction referencing only real files>",
      "files_involved": ["<file path from valid paths list>"]
    }}
  ],
  "common_mistakes": [
    "<specific pitfall 1>",
    "<specific pitfall 2>"
  ],
  "dependency_chain": {json.dumps(dep_chain)}
}}"""

    try:
        resp   = str(Settings.llm.complete(prompt, format="json"))
        result = extract_json(resp)

        if not result:
            logger.warning("Reasoning agent returned no valid JSON; using fallback.")
            result = {
                "where_to_start":     retrieved_files[0] if retrieved_files else "",
                "what_to_read_first": retrieved_files[:2],
                "explanation": (
                    "The AI retrieved relevant files but could not format a structured guide. "
                    "Please review the files in the retrieval section manually."
                ),
                "logic_trace":       ["Manual review required."],
                "contribution_path": [{
                    "step": 1,
                    "title": "Review retrieved files",
                    "description": "Open the files listed in the retrieval section.",
                    "files_involved": retrieved_files[:2],
                }],
                "common_mistakes":   ["N/A"],
                "dependency_chain":  dep_chain,
            }
        else:
            # Always override dep_chain with the statically computed value
            result["dependency_chain"] = dep_chain

    except Exception as exc:
        logger.error(f"Reasoning agent error: {exc}")
        result = {
            "explanation":        f"Failed to generate guide: {exc}",
            "where_to_start":     "",
            "what_to_read_first": [],
            "logic_trace":        [],
            "contribution_path":  [],
            "common_mistakes":    [],
            "dependency_chain":   dep_chain,
        }

    if include_patch:
        result["suggested_patch"] = _generate_patch(retrieved_files, sources, issue_full)

    return result


# ---------------------------------------------------------------------------
# Q&A Agent
# ---------------------------------------------------------------------------

def run_repo_qa(engine_bundle: dict, question: str) -> dict:
    """
    Answer a free-form question about the repository using the RAG pipeline.

    Grounding: instructs the model to cite only retrieved files and flag gaps.
    """
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
        logger.error(f"QA agent error: {exc}")
        answer = "I encountered an error while generating an answer."

    return {
        "answer":         answer,
        "relevant_files": retrieved_files,
    }


# ---------------------------------------------------------------------------
# Async background indexing helper (used by api.py)
# ---------------------------------------------------------------------------

async def build_query_engine_async(content: str, repo_name: str) -> dict:
    """
    Run build_query_engine in a thread pool so the FastAPI event loop stays
    responsive during the CPU/GPU-heavy embedding phase.
    """
    return await asyncio.to_thread(build_query_engine, content, repo_name)