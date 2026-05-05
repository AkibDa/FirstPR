import os
import tempfile
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from schemas import RepoLoadRequest, AnalyzeRequest
from utils import validate_github_url, get_repo_name
from gitingest import ingest_async
from services import (
    repo_cache,
    build_query_engine,
    run_issue_analyzer,
    run_retrieval_agent,
    run_reasoning_agent
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

@router.post("/load-repo")
async def load_repo(req: RepoLoadRequest):
  if not validate_github_url(req.repo_url):
    raise HTTPException(400, "Invalid GitHub URL")

  cache_key = req.repo_url.rstrip("/")
  if cache_key in repo_cache:
    return {
      "status": "cached",
      "repo_name": get_repo_name(req.repo_url),
      "summary": repo_cache[cache_key]["summary"],
      "tree": repo_cache[cache_key]["tree"],
    }

  try:
    with tempfile.TemporaryDirectory() as tmp_dir:
      repo_path = os.path.join(tmp_dir, "cloned_repo")

      logger.info(f"Manually cloning {req.repo_url} without timeout...")
      process = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth=1", req.repo_url, repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
      )
      stdout, stderr = await process.communicate()

      if process.returncode != 0:
        error_msg = stderr.decode().strip()
        raise Exception(f"Git clone failed: {error_msg}")

      logger.info("Clone successful. Passing local path to gitingest...")

      summary, tree, content = await ingest_async(repo_path)

  except Exception as e:
    logger.error(f"Ingestion error: {e}")
    raise HTTPException(500, f"Failed to ingest repo: {str(e)}")

  try:
    qe = build_query_engine(content, get_repo_name(req.repo_url))
  except Exception as e:
    logger.error(f"index build error: {e}")
    raise HTTPException(500, f"Failed to build index: {str(e)}")

  repo_cache[cache_key] = {
    "summary": summary,
    "tree": tree,
    "content": content,
    "query_engine": qe,
  }

  return {
    "status": "loaded",
    "repo_name": get_repo_name(req.repo_url),
    "summary": summary,
    "tree": tree,
  }

@router.post("/analyze-issue")
async def analyze_issue(req: AnalyzeRequest):
  if not validate_github_url(req.repo_url):
    raise HTTPException(400, "Invalid GitHub URL")

  cache_key = req.repo_url.rstrip("/")
  if cache_key not in repo_cache:
    raise HTTPException(400, "Repository not loaded. Call /api/load-repo first.")

  entry = repo_cache[cache_key]
  qe = entry["query_engine"]
  tree = entry["tree"]
  content = entry["content"]

  issue_full = f"Title: {req.issue_title}\n\n{req.issue_text}" if req.issue_title else req.issue_text

  analysis = run_issue_analyzer(tree, issue_full)

  retrieval = run_retrieval_agent(qe, issue_full)

  retrieved_files = []
  if "relevant_files" in retrieval:
    for f in retrieval["relevant_files"]:
      if "path" in f:
        retrieved_files.append(f["path"])

  reasoning = run_reasoning_agent(tree, retrieved_files, content, issue_full)

  return {
    "repo_name": get_repo_name(req.repo_url),
    "analysis": analysis,
    "retrieval": retrieval,
    "reasoning": reasoning,
  }

@router.get("/health")
async def health():
    return {"status": "ok", "cached_repos": list(repo_cache.keys())}
