import asyncio
import logging
import os
import tempfile
import traceback
import subprocess
import httpx
import re
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
import json

from schemas import AnalyzeRequest, RepoLoadRequest, RepoQARequest
from utils import validate_github_url, get_repo_name, fetch_github_issue
from gitingest import ingest_async
from services import (
    repo_cache,
    build_query_engine_async,
    run_issue_analyzer,
    run_retrieval_agent,
    run_reasoning_agent,
    run_repo_qa,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_indexing_in_progress: dict[str, asyncio.Event] = {}

async def _stream_status(steps: list[tuple[str, any]]) -> AsyncGenerator[str, None]:
    """
    Yield newline-delimited JSON status events for SSE / chunked streaming.

    Each step is a (status_label, coroutine_or_value) tuple.  The coroutine is
    awaited and its result is sent in the final ``done`` event.
    """
    for label, coro in steps:
        yield json.dumps({"status": label}) + "\n"
        await asyncio.sleep(0)   # flush to client
        if asyncio.iscoroutine(coro):
            result = await coro
        else:
            result = coro
    yield json.dumps({"status": "done", "result": result}) + "\n"

async def check_repo_size(repo_url: str, max_mb: int = 500) -> bool:
  """Check the GitHub API to ensure the repo isn't too massive to process."""
  try:
    from utils import parse_github_issue_url
    # Reusing the regex logic to grab owner/repo
    pattern = r"https://github\.com/([^/]+)/([^/]+)"
    m = re.match(pattern, repo_url.rstrip("/"))
    if not m:
      return True  # Fallback if URL parsing fails

    owner, repo = m.group(1), m.group(2)
    api_url = f"[https://api.github.com/repos/](https://api.github.com/repos/){owner}/{repo}"

    async with httpx.AsyncClient(timeout=10) as client:
      resp = await client.get(api_url)
      if resp.status_code == 200:
        size_kb = resp.json().get("size", 0)
        if (size_kb / 1024) > max_mb:
          raise HTTPException(
            400,
            f"Repository is too large ({(size_kb / 1024):.1f}MB). Maximum allowed is {max_mb}MB."
          )
    return True
  except Exception as e:
    logger.warning(f"Could not verify repo size: {e}")
    return True

@router.post("/load-repo")
async def load_repo(req: RepoLoadRequest):
    """
    Clone and index a GitHub repository.

    Behaviour:
    - Already in memory → returns immediately as ``"cached"``.
    - Currently being indexed by another request → waits for it to finish.
    - ChromaDB collection exists but not in memory → reloads without cloning.
    - Fresh repo → clones, ingests, indexes asynchronously.

    Returns progressive JSON status events as a streaming response so the
    frontend can show live progress feedback.
    """
    if not validate_github_url(req.repo_url):
        raise HTTPException(400, "Invalid GitHub URL")

    await check_repo_size(req.repo_url, max_mb=300)

    cache_key = req.repo_url.rstrip("/")
    repo_name = get_repo_name(req.repo_url)

    if cache_key in repo_cache:
        entry = repo_cache[cache_key]
        return {
            "status":    "cached",
            "repo_name": repo_name,
            "summary":   entry["summary"],
            "tree":      entry["tree"],
        }

    if cache_key in _indexing_in_progress:
        logger.info(f"Waiting for in-progress indexing of {cache_key} …")
        await _indexing_in_progress[cache_key].wait()
        if cache_key in repo_cache:
            entry = repo_cache[cache_key]
            return {
                "status":    "cached",
                "repo_name": repo_name,
                "summary":   entry["summary"],
                "tree":      entry["tree"],
            }
        raise HTTPException(500, "Indexing finished but repo not found in cache.")

    done_event = asyncio.Event()
    _indexing_in_progress[cache_key] = done_event

    async def _do_index() -> dict:
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                repo_path = os.path.join(tmp_dir, "cloned_repo")
                logger.info(f"Cloning {req.repo_url} …")

                process = await asyncio.to_thread(
                    subprocess.run,
                    ["git", "clone", "--depth=1", req.repo_url, repo_path],
                    capture_output=True,
                    text=True,
                )

                if process.returncode != 0:
                    raise RuntimeError(f"Git clone failed: {process.stderr.strip()}")

                logger.info("Clone done. Ingesting …")
                summary, tree, content = await ingest_async(repo_path)

            logger.info("Building index …")
            engine_bundle = await build_query_engine_async(content, repo_name)

            repo_cache[cache_key] = {
                "summary":       summary,
                "tree":          tree,
                "engine_bundle": engine_bundle,
            }
            return {"status": "loaded", "repo_name": repo_name, "summary": summary, "tree": tree}

        except Exception as exc:
            logger.exception("FULL INGESTION TRACEBACK")
            traceback.print_exc()
            raise exc
        finally:
            done_event.set()
            _indexing_in_progress.pop(cache_key, None)

    return StreamingResponse(
        _progressive_load(cache_key, repo_name, _do_index),
        media_type="application/x-ndjson",
    )

async def _progressive_load(
    cache_key: str,
    repo_name: str,
    index_coro_factory,
) -> AsyncGenerator[str, None]:
    """Yield newline-delimited JSON progress events while indexing runs."""
    yield json.dumps({"status": "cloning", "repo_name": repo_name}) + "\n"
    await asyncio.sleep(0)
    try:
        result = await index_coro_factory()
        yield json.dumps({"status": "done", **result}) + "\n"
    except Exception as exc:
        yield json.dumps({"status": "error", "detail": repr(exc)}) + "\n"

@router.post("/analyze-issue")
async def analyze_issue(
    req: AnalyzeRequest,
    generate_patch: bool = Query(
        default=False,
        description="Set to true to include an optional unified diff in the response.",
    ),
    stream: bool = Query(
        default=False,
        description="Set to true for newline-delimited JSON progress events.",
    ),
):
    """
    Run the full multi-agent pipeline against a loaded repository.

    With ``stream=true`` the response is a newline-delimited JSON stream where
    each line carries a ``status`` field (``analyzing`` → ``retrieving`` →
    ``reasoning`` → ``done``).  With ``stream=false`` (default) the full result
    is returned as a single JSON object.
    """
    if not validate_github_url(req.repo_url):
        raise HTTPException(400, "Invalid GitHub URL")

    cache_key = req.repo_url.rstrip("/")
    if cache_key not in repo_cache:
        raise HTTPException(
            400,
            "Repository not loaded. Call POST /api/load-repo first.",
        )

    entry         = repo_cache[cache_key]
    engine_bundle = entry["engine_bundle"]
    tree          = entry["tree"]
    sources: dict = engine_bundle["sources"]

    issue_title = req.issue_title or ""
    issue_text  = req.issue_text  or ""

    if req.issue_url:
        try:
            fetched     = await fetch_github_issue(req.issue_url)
            issue_title = fetched["title"]
            issue_text  = fetched["body"]
            labels_str  = ", ".join(fetched.get("labels", []))
            if labels_str:
                issue_text += f"\n\nLabels: {labels_str}"
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            logger.error(f"GitHub issue fetch failed: {exc}")
            raise HTTPException(502, f"Could not fetch GitHub issue: {exc}")

    issue_full = f"Title: {issue_title}\n\n{issue_text}" if issue_title else issue_text

    if not issue_full.strip():
        raise HTTPException(400, "Issue body is empty.")

    repo_name = get_repo_name(req.repo_url)

    async def _run_pipeline():
        # Run analysis and retrieval concurrently (both are read-only)
        analysis_task  = asyncio.to_thread(run_issue_analyzer, tree, issue_full)
        retrieval_task = asyncio.to_thread(run_retrieval_agent, engine_bundle, issue_full)

        analysis, retrieval = await asyncio.gather(analysis_task, retrieval_task)

        retrieved_file_paths = [
            f["path"] for f in retrieval.get("relevant_files", []) if "path" in f
        ]
        reranker_meta = retrieval.get("reranker") or {}

        reasoning = await asyncio.to_thread(
            run_reasoning_agent,
            tree=tree,
            retrieved_files=retrieved_file_paths,
            sources=sources,
            issue_full=issue_full,
            include_patch=generate_patch,
            reranker_meta=reranker_meta,
        )

        return {
            "repo_name": repo_name,
            "issue": {
                "title":  issue_title,
                "source": req.issue_url or "manual",
            },
            "analysis":  analysis,
            "retrieval": retrieval,
            "reasoning": reasoning,
        }

    if stream:
        return StreamingResponse(
            _streamed_pipeline(issue_full, _run_pipeline),
            media_type="application/x-ndjson",
        )

    return await _run_pipeline()

async def _streamed_pipeline(issue_full: str, pipeline_coro_factory) -> AsyncGenerator[str, None]:
    """Emit progressive status events, then the final result."""
    yield json.dumps({"status": "analyzing"}) + "\n"
    await asyncio.sleep(0)
    yield json.dumps({"status": "retrieving"}) + "\n"
    await asyncio.sleep(0)
    yield json.dumps({"status": "reasoning"}) + "\n"
    await asyncio.sleep(0)
    try:
        result = await pipeline_coro_factory()
        yield json.dumps({"status": "done", "result": result}) + "\n"
    except Exception as exc:
        yield json.dumps({"status": "error", "detail": repr(exc)}) + "\n"

@router.post("/ask")
async def ask_repo(req: RepoQARequest):
    """Ask a general question about a loaded repository."""
    if not validate_github_url(req.repo_url):
        raise HTTPException(400, "Invalid GitHub URL")

    cache_key = req.repo_url.rstrip("/")
    if cache_key not in repo_cache:
        raise HTTPException(
            400,
            "Repository not loaded. Call POST /api/load-repo first.",
        )

    entry         = repo_cache[cache_key]
    engine_bundle = entry["engine_bundle"]

    qa_result = await asyncio.to_thread(run_repo_qa, engine_bundle, req.question)

    return {
        "repo_name":      get_repo_name(req.repo_url),
        "question":       req.question,
        "answer":         qa_result["answer"],
        "relevant_files": qa_result["relevant_files"],
    }

@router.get("/repo-status")
async def repo_status():
    """Return metadata about every repository currently held in memory."""
    repos = []
    for url, entry in repo_cache.items():
        bundle  = entry.get("engine_bundle", {})
        sources = bundle.get("sources", {})
        repos.append({
            "url":        url,
            "repo_name":  get_repo_name(url),
            "file_count": len(sources),
            "has_bm25":   bundle.get("bm25") is not None,
        })
    return {"cached_repos": repos}

@router.get("/health")
async def health():
    in_progress = list(_indexing_in_progress.keys())
    return {
        "status":       "ok",
        "cached_repos": list(repo_cache.keys()),
        "indexing":     in_progress,
    }
