import os
import gc
import uuid
import logging
import tempfile
from typing import Optional
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gitingest import ingest
from llama_index.core import Settings, PromptTemplate, VectorStoreIndex, SimpleDirectoryReader
from llama_index.core.node_parser import MarkdownNodeParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GitHub Issue Navigator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache: repo_url -> {"summary", "tree", "content", "query_engine"}
repo_cache: dict = {}


class AnalyzeRequest(BaseModel):
    repo_url: str
    issue_text: str
    issue_title: Optional[str] = ""


class RepoLoadRequest(BaseModel):
    repo_url: str


def validate_github_url(url: str) -> bool:
    return url.startswith(("https://github.com/", "http://github.com/"))


def get_repo_name(url: str) -> str:
    return url.rstrip("/").split("/")[-1].replace(".git", "")


def build_query_engine(content: str, repo_name: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"{repo_name}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        loader = SimpleDirectoryReader(input_dir=tmp)
        docs = loader.load_data()
        node_parser = MarkdownNodeParser()
        index = VectorStoreIndex.from_documents(
            documents=docs,
            transformations=[node_parser],
            show_progress=False,
        )
        query_engine = index.as_query_engine(streaming=False)
        return query_engine


@app.post("/api/load-repo")
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
        summary, tree, content = ingest(req.repo_url)
    except Exception as e:
        logger.error(f"gitingest error: {e}")
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


@app.post("/api/analyze-issue")
async def analyze_issue(req: AnalyzeRequest):
    if not validate_github_url(req.repo_url):
        raise HTTPException(400, "Invalid GitHub URL")

    cache_key = req.repo_url.rstrip("/")
    if cache_key not in repo_cache:
        raise HTTPException(400, "Repository not loaded. Call /api/load-repo first.")

    entry = repo_cache[cache_key]
    qe = entry["query_engine"]
    tree = entry["tree"]

    issue_full = f"Title: {req.issue_title}\n\n{req.issue_text}" if req.issue_title else req.issue_text

    # --- Agent 1: Issue Analyzer ---
    analysis_prompt = f"""
You are an expert open-source contributor mentor. Analyze the following GitHub issue and return a structured JSON response.

Repository structure:
{tree[:3000]}

Issue:
{issue_full}

Return ONLY valid JSON (no markdown, no code fences) with this structure:
{{
  "issue_type": "bug|feature|docs|refactor|test",
  "difficulty": "beginner|intermediate|advanced",
  "difficulty_reason": "brief explanation",
  "root_cause_hypothesis": "what might be causing this",
  "required_skills": ["skill1", "skill2"],
  "estimated_hours": "1-2|2-4|4-8|8-16|16+",
  "affected_areas": ["area1", "area2"]
}}
"""
    try:
        analysis_resp = qe.query(analysis_prompt)
        import json, re
        raw = str(analysis_resp)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        analysis = json.loads(json_match.group()) if json_match else {}
    except Exception as e:
        logger.warning(f"Issue analysis failed: {e}")
        analysis = {}

    # --- Agent 2: Retrieval Agent ---
    retrieval_prompt = f"""
You are a code retrieval expert. Given this GitHub issue, identify the most relevant files and functions.

Issue:
{issue_full}

Analyze the repository and return ONLY valid JSON (no markdown):
{{
  "relevant_files": [
    {{"path": "src/example.py", "relevance": "high|medium|low", "reason": "why this file matters"}},
    {{"path": "src/utils.py", "relevance": "medium", "reason": "..."}}
  ],
  "key_functions": ["functionName1", "functionName2"],
  "search_keywords": ["keyword1", "keyword2", "keyword3"]
}}
"""
    try:
        retrieval_resp = qe.query(retrieval_prompt)
        raw2 = str(retrieval_resp)
        json_match2 = re.search(r'\{.*\}', raw2, re.DOTALL)
        retrieval = json.loads(json_match2.group()) if json_match2 else {}
    except Exception as e:
        logger.warning(f"Retrieval agent failed: {e}")
        retrieval = {}

    # --- Agent 3: Code Reasoning Agent ---
    reasoning_prompt = f"""
You are an expert code mentor helping a beginner open-source contributor solve a GitHub issue.

Repository tree:
{tree[:2000]}

Issue:
{issue_full}

Provide a clear, actionable contribution guide. Return ONLY valid JSON (no markdown):
{{
  "explanation": "Plain English explanation of what the code does and why this issue occurs",
  "logic_trace": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
  "contribution_path": [
    {{"step": 1, "action": "what to do", "file": "which file", "details": "specifics"}},
    {{"step": 2, "action": "...", "file": "...", "details": "..."}}
  ],
  "code_snippet": "// Example fix or starting point\n// (pseudocode or actual code)",
  "testing_advice": "How to test the fix",
  "gotchas": ["potential pitfall 1", "potential pitfall 2"],
  "resources": ["relevant doc or concept 1", "relevant doc or concept 2"]
}}
"""
    try:
        reasoning_resp = qe.query(reasoning_prompt)
        raw3 = str(reasoning_resp)
        json_match3 = re.search(r'\{.*\}', raw3, re.DOTALL)
        reasoning = json.loads(json_match3.group()) if json_match3 else {}
    except Exception as e:
        logger.warning(f"Reasoning agent failed: {e}")
        reasoning = {"explanation": str(reasoning_resp) if 'reasoning_resp' in dir() else "Analysis unavailable"}

    return {
        "repo_name": get_repo_name(req.repo_url),
        "analysis": analysis,
        "retrieval": retrieval,
        "reasoning": reasoning,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "cached_repos": list(repo_cache.keys())}