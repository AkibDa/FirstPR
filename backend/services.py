from __future__ import annotations

import json
import logging
import re
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

Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")
Settings.llm = Ollama(
    model="llama3.2:3b",
    base_url="http://localhost:11434",
    request_timeout=600.0,
    context_window=8192,
)

def _split_repo_content(content: str) -> List[Tuple[str, str]]:
    """
    Split the gitingest 'content' blob into (file_path, source_code) pairs.
    Handles the separator lines gitingest emits.
    """
    parts = re.split(
        r"={48}\n(?:File|FILE|file):\s*", content
    )
    files: List[Tuple[str, str]] = []
    for part in parts:
        if not part.strip() or "Directory structure:" in part:
            continue
        subparts = part.split("\n" + "=" * 48 + "\n", 1)
        if len(subparts) == 2:
            fp   = subparts[0].strip()
            code = subparts[1].strip()
            files.append((fp, code))
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
    }

def build_query_engine(content: str, repo_name: str) -> dict:
    """
    Build (or reload) a persistent vector index for *repo_name*.

    Returns a dict with keys:
        ``vector_index``   – LlamaIndex VectorStoreIndex
        ``bm25``           – BM25Okapi instance
        ``bm25_nodes``     – list of NodeWithScore-like dicts (for BM25 lookup)
        ``sources``        – Dict[file_path, source_code]
    """
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_name)[:60] or "repo"

    collection = _chroma_client.get_or_create_collection(safe_name)
    vector_store    = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    files   = _split_repo_content(content)
    sources = {fp: src for fp, src in files}

    if collection.count() > 0:
        logger.info(f"Reusing existing Chroma collection '{safe_name}' ({collection.count()} chunks).")
        index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )
    else:
        logger.info(f"Building new Chroma collection '{safe_name}' from {len(files)} files…")
        docs = []
        for fp, src in files:
            meta = _rich_metadata(fp, src)
            docs.append(Document(text=src, metadata=meta))

        splitter = SentenceSplitter(chunk_size=512, chunk_overlap=64)
        index = VectorStoreIndex.from_documents(
            documents=docs,
            storage_context=storage_context,
            transformations=[splitter],
            show_progress=False,
        )

    bm25_corpus = []
    bm25_nodes  = []
    for fp, src in files:
        tokens = re.findall(r"[a-zA-Z_]\w*", src)
        bm25_corpus.append(tokens)
        bm25_nodes.append({"file_path": fp, "text": src[:6000]})

    bm25 = BM25Okapi(bm25_corpus) if bm25_corpus else None

    return {
        "vector_index": index,
        "bm25":         bm25,
        "bm25_nodes":   bm25_nodes,
        "sources":      sources,
    }

def extract_json(text: str) -> dict:
    """
    Safely extract the first JSON object from an LLM response.

    Handles:
    - ```json ... ``` markdown fences
    - ```  ... ``` plain fences
    - Leading preamble / trailing commentary
    - Truncated JSON (attempts to close unclosed braces)
    """
    if not text:
        return {}

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start == -1:
        logger.warning("extract_json: no '{' found in LLM output")
        return {}

    depth = 0
    end   = -1
    in_string = False
    escape    = False
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
        logger.warning(f"extract_json: JSON decode error after extraction: {exc}")
        return {}

def run_issue_analyzer(tree: str, issue_full: str) -> dict:
    """Categorise the issue: type, difficulty, required skills, affected areas."""
    prompt = f"""
You are an expert open-source contributor mentor. Analyse the GitHub issue below
and return ONLY valid JSON (no markdown fences, no extra text).

Repository structure (truncated):
{tree[:3000]}

Issue:
{issue_full}

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
}}
"""
    try:
        resp = Settings.llm.complete(prompt)
        return extract_json(str(resp))
    except Exception as exc:
        logger.warning(f"Issue analysis failed: {exc}")
        return {}

def _explain_why(
    file_path: str,
    source: str,
    query: str,
    score: Optional[float],
    method: str,
) -> str:
    """
    Ask the LLM to explain in plain English why *file_path* is relevant
    to *query*.  Falls back to a template if the LLM call fails.
    """
    snippet = source[:800]
    prompt = f"""
You are a code mentor. In one or two plain-English sentences, explain why the
file below is relevant to the following issue. Be specific: mention function
names, class names, or logic that connects the file to the issue.

Issue summary:
{query[:400]}

File: {file_path}
Code snippet:
{snippet}

Reply with ONLY the explanation, no bullet points, no JSON.
"""
    try:
        resp = str(Settings.llm.complete(prompt)).strip()
        return resp if resp else f"Retrieved via {method} (score: {score:.2f})."
    except Exception:
        method_label = method.capitalize()
        score_str = f"{score:.2f}" if score is not None else "n/a"
        return f"{method_label} match (score {score_str}): file contains code related to the issue."


def run_retrieval_agent(engine_bundle: dict, issue_full: str) -> dict:
    """
    Hybrid retrieval: combine vector similarity with BM25 keyword search.

    Returns a dict with ``relevant_files`` (list of rich file dicts).
    """
    vector_index: VectorStoreIndex = engine_bundle["vector_index"]
    bm25: Optional[BM25Okapi]      = engine_bundle["bm25"]
    bm25_nodes: list               = engine_bundle["bm25_nodes"]
    sources: Dict[str, str]        = engine_bundle["sources"]

    seen:           Dict[str, Tuple[float, str]] = {}   # path → (score, method)

    try:
        retriever = vector_index.as_retriever(similarity_top_k=6)
        nodes: List[NodeWithScore] = retriever.retrieve(issue_full)
        for node in nodes:
            fp    = node.metadata.get("file_path", "")
            score = node.score or 0.0
            if fp and (fp not in seen or score > seen[fp][0]):
                seen[fp] = (score, "semantic")
    except Exception as exc:
        logger.warning(f"Vector retrieval failed: {exc}")

    if bm25 and bm25_nodes:
        query_tokens = re.findall(r"[a-zA-Z_]\w*", issue_full)
        bm25_scores  = bm25.get_scores(query_tokens)
        top_k        = min(6, len(bm25_scores))
        top_indices  = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k]
        for idx in top_indices:
            if bm25_scores[idx] < 0.5:
                continue
            fp    = bm25_nodes[idx]["file_path"]
            score = float(bm25_scores[idx])
            if fp not in seen or (score > seen[fp][0] and seen[fp][1] == "semantic"):
                seen[fp] = (score, "bm25")

    relevant_files = []
    for fp, (score, method) in list(seen.items())[:8]:
        src     = sources.get(fp, "")
        symbols = extract_symbols(src)
        role    = classify_file_role(fp, src)
        reason  = _explain_why(fp, src, issue_full, score, method)
        relevant_files.append({
            "path":      fp,
            "relevance": "high" if score >= 1.0 else "medium",
            "score":     round(score, 3),
            "method":    method,
            "reason":    reason,
            "functions": symbols["functions"],
            "classes":   symbols["classes"],
            "role":      role,
        })

    relevant_files.sort(key=lambda f: (f["method"] != "semantic", -f["score"]))

    keyword_text = re.sub(r"^Title:[^\n]*\n", "", issue_full, flags=re.IGNORECASE).strip()
    _STOPWORDS = {"this", "that", "with", "from", "have", "will", "when", "what",
                  "which", "there", "their", "about", "would", "could", "should"}
    raw_keywords = re.findall(r"[A-Z][a-z]+(?:[A-Z][a-z]*)+|[a-z_]{4,}", keyword_text)
    keywords = [kw for kw in dict.fromkeys(raw_keywords) if kw not in _STOPWORDS][:10]

    return {
        "relevant_files":   relevant_files,
        "key_functions":    list({fn for f in relevant_files for fn in f["functions"]})[:10],
        "search_keywords":  keywords,
    }

def _build_code_context(
    retrieved_files: List[str],
    sources: Dict[str, str],
    max_chars_per_file: int = 3500,
) -> str:
    """Assemble a readable code context block for the reasoning prompt."""
    parts = []
    for fp in retrieved_files:
        src = sources.get(fp, "")
        if not src:
            continue
        parts.append(f"--- File: {fp} ---\n{src[:max_chars_per_file]}")
    return "\n\n".join(parts)

def _generate_patch(
    retrieved_files: List[str],
    sources: Dict[str, str],
    issue_full: str,
) -> Optional[dict]:
    """
    Ask the LLM to produce a unified diff for the most relevant file.
    Returns ``{"file_path": ..., "diff": ...}`` or None.
    """
    if not retrieved_files:
        return None

    primary_file = retrieved_files[0]
    original     = sources.get(primary_file, "")
    if not original:
        return None

    prompt = f"""
You are a senior engineer. Given the issue and the file below, produce a minimal
unified diff (--- a/file  +++ b/file format) that fixes or implements the issue.
Output ONLY the diff, no explanation, no markdown fences.

Issue:
{issue_full[:600]}

File ({primary_file}):
{original[:3000]}
"""
    try:
        diff_text = str(Settings.llm.complete(prompt)).strip()
        # Accept only if it looks like a real diff
        if diff_text.startswith(("---", "@@", "diff")):
            return {"file_path": primary_file, "diff": diff_text}
    except Exception as exc:
        logger.warning(f"Patch generation failed: {exc}")
    return None


def run_reasoning_agent(
    tree: str,
    retrieved_files: List[str],
    sources: Dict[str, str],
    issue_full: str,
    include_patch: bool = False,
) -> dict:
    """
    Mentorship-focused reasoning agent.

    Produces a structured guide with:
    - where_to_start
    - what_to_read_first
    - explanation
    - logic_trace (cross-file)
    - contribution_path (ordered steps)
    - common_mistakes
    - dependency_chain
    - suggested_patch  (if include_patch=True)
    """
    code_context = _build_code_context(retrieved_files, sources)

    dep_chain: List[str] = []
    for fp in retrieved_files[:3]:
        dep_chain.extend(build_dependency_chain(fp, sources))
    dep_chain = list(dict.fromkeys(dep_chain))

    file_roles = []
    for fp in retrieved_files:
        src  = sources.get(fp, "")
        role = classify_file_role(fp, src)
        file_roles.append(f"  - {fp}  [{role}]")
    file_role_str = "\n".join(file_roles) if file_roles else "  (none)"

    prompt = f"""
You are a patient, expert open-source mentor helping a BEGINNER make their very
first contribution. Use the repository tree, the issue, and the relevant source
code below to produce a comprehensive, beginner-friendly contribution guide.

Repository tree (truncated):
{tree[:1500]}

File roles detected:
{file_role_str}

Issue:
{issue_full}

Relevant source code:
{code_context}

Dependency / import chain detected:
{chr(10).join(dep_chain) if dep_chain else "N/A"}

Return ONLY valid JSON (no markdown fences, no extra text) with EXACTLY this schema:
{{
  "where_to_start": "The exact file path AND function name a beginner should open first (e.g. 'app.py → load_image_pipeline()').",
  "what_to_read_first": [
    "file_path_1 — one sentence on what to look for",
    "file_path_2 — one sentence on what to look for"
  ],
  "explanation": "3-5 sentences in plain English describing what the relevant code currently does, why it matters for this issue, and how the pieces fit together.",
  "logic_trace": [
    "Step 1: (file.py) What happens here and why.",
    "Step 2: (file.py) What happens next.",
    "Step 3: (file.py) How it connects to the issue."
  ],
  "contribution_path": [
    {{
      "step": 1,
      "title": "Short imperative title (e.g. 'Understand the existing model loading logic')",
      "description": "Detailed, beginner-friendly instruction. Mention exact function or line references where helpful.",
      "files_involved": ["path/to/file.py"]
    }},
    {{
      "step": 2,
      "title": "...",
      "description": "...",
      "files_involved": ["..."]
    }},
    {{
      "step": 3,
      "title": "...",
      "description": "...",
      "files_involved": ["..."]
    }}
  ],
  "common_mistakes": [
    "Specific pitfall 1 a beginner is likely to hit on THIS issue.",
    "Specific pitfall 2.",
    "Specific pitfall 3."
  ],
  "dependency_chain": {json.dumps(dep_chain)}
}}

Rules:
- contribution_path MUST have at least 3 steps.
- what_to_read_first MUST contain file paths, not function names.
- explanation MUST be 3-5 sentences, not a single line.
- Every string value must be plain English; no code blocks inside JSON strings.
"""
    try:
        resp   = str(Settings.llm.complete(prompt))
        result = extract_json(resp)
    except Exception as exc:
        logger.error(f"Reasoning agent error: {exc}")
        result = {
            "explanation":        f"Failed to generate guide from local model: {exc}",
            "where_to_start":     "",
            "what_to_read_first": [],
            "logic_trace":        [],
            "contribution_path":  [],
            "common_mistakes":    [],
            "dependency_chain":   dep_chain,
        }

    if dep_chain:
        result["dependency_chain"] = dep_chain

    if include_patch:
        patch = _generate_patch(retrieved_files, sources, issue_full)
        result["suggested_patch"] = patch

    return result
