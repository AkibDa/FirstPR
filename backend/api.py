import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, HTTPException, Query

from schemas import AnalyzeRequest, RepoLoadRequest
from utils import validate_github_url, get_repo_name, fetch_github_issue
from gitingest import ingest_async
from services import (
    repo_cache,
    build_query_engine,
    run_issue_analyzer,
    run_retrieval_agent,
    run_reasoning_agent,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

@router.post("/load-repo")
async def load_repo(req: RepoLoadRequest):
    """
    Clone and index a GitHub repository.

    If the repository has already been indexed in the persistent ChromaDB store
    and is present in the in-memory cache, the endpoint returns immediately with
    status ``"cached"``.  If it was indexed in a previous server run (ChromaDB
    collection exists) but is not in memory yet, the index is reloaded without
    re-cloning.  Otherwise the repo is cloned, ingested, and indexed from scratch.
    """
    if not validate_github_url(req.repo_url):
        raise HTTPException(400, "Invalid GitHub URL")

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

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = os.path.join(tmp_dir, "cloned_repo")
            logger.info(f"Cloning {req.repo_url} …")
            process = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth=1", req.repo_url, repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(f"Git clone failed: {stderr.decode().strip()}")

            logger.info("Clone successful. Ingesting with gitingest…")
            summary, tree, content = await ingest_async(repo_path)
    except Exception as exc:
        logger.error(f"Ingestion error: {exc}")
        raise HTTPException(500, f"Failed to ingest repo: {exc}")

    try:
        engine_bundle = build_query_engine(content, repo_name)
    except Exception as exc:
        logger.error(f"Index build error: {exc}")
        raise HTTPException(500, f"Failed to build index: {exc}")

    repo_cache[cache_key] = {
        "summary":       summary,
        "tree":          tree,
        "engine_bundle": engine_bundle,   # contains vector_index, bm25, sources
    }

    return {
        "status":    "loaded",
        "repo_name": repo_name,
        "summary":   summary,
        "tree":      tree,
    }

@router.post("/analyze-issue")
async def analyze_issue(
    req: AnalyzeRequest,
    generate_patch: bool = Query(
        default=False,
        description="Set to true to include an optional unified diff in the response.",
    ),
):
    """
    Run the full multi-agent pipeline against a loaded repository.

    The issue can be supplied as:
    - ``issue_url``  – a GitHub issue URL  (e.g. https://github.com/owner/repo/issues/42)
    - ``issue_text`` – pasted text (with optional ``issue_title``)
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
            fetched    = await fetch_github_issue(req.issue_url)
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

    analysis  = run_issue_analyzer(tree, issue_full)
    retrieval = run_retrieval_agent(engine_bundle, issue_full)

    retrieved_file_paths = [
        f["path"] for f in retrieval.get("relevant_files", []) if "path" in f
    ]

    reasoning = run_reasoning_agent(
        tree=tree,
        retrieved_files=retrieved_file_paths,
        sources=sources,
        issue_full=issue_full,
        include_patch=generate_patch,
    )

    return {
        "repo_name": get_repo_name(req.repo_url),
        "issue": {
            "title":  issue_title,
            "source": req.issue_url or "manual",
        },
        "analysis":  analysis,
        "retrieval": retrieval,
        "reasoning": reasoning,
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
    return {"status": "ok", "cached_repos": list(repo_cache.keys())}
