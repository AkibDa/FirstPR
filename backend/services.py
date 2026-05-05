import os
import tempfile
import json
import re
import logging
from gitingest import ingest
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.core.node_parser import MarkdownNodeParser

logger = logging.getLogger(__name__)

# In-memory cache
repo_cache: dict = {}

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
        return index.as_query_engine(streaming=False)

def run_issue_analyzer(qe, tree: str, issue_full: str) -> dict:
    prompt = f"""
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
        resp = qe.query(prompt)
        json_match = re.search(r'\{.*\}', str(resp), re.DOTALL)
        return json.loads(json_match.group()) if json_match else {}
    except Exception as e:
        logger.warning(f"Issue analysis failed: {e}")
        return {}

def run_retrieval_agent(qe, issue_full: str) -> dict:
    prompt = f"""
You are a code retrieval expert. Given this GitHub issue, identify the most relevant files and functions.

Issue:
{issue_full}

Analyze the repository and return ONLY valid JSON (no markdown):
{{
  "relevant_files": [
    {{"path": "src/example.py", "relevance": "high|medium|low", "reason": "why this file matters"}}
  ],
  "key_functions": ["functionName1", "functionName2"],
  "search_keywords": ["keyword1", "keyword2", "keyword3"]
}}
"""
    try:
        resp = qe.query(prompt)
        json_match = re.search(r'\{.*\}', str(resp), re.DOTALL)
        return json.loads(json_match.group()) if json_match else {}
    except Exception as e:
        logger.warning(f"Retrieval agent failed: {e}")
        return {}

def run_reasoning_agent(qe, tree: str, issue_full: str) -> dict:
    prompt = f"""
You are an expert code mentor helping a beginner open-source contributor solve a GitHub issue.

Repository tree:
{tree[:2000]}

Issue:
{issue_full}

Provide a clear, actionable contribution guide. Return ONLY valid JSON (no markdown):
{{
  "explanation": "Plain English explanation of what the code does...",
  "logic_trace": ["Step 1: ..."],
  "contribution_path": [
    {{"step": 1, "action": "what to do", "file": "which file", "details": "specifics"}}
  ],
  "code_snippet": "// Example fix",
  "testing_advice": "How to test the fix",
  "gotchas": ["potential pitfall"],
  "resources": ["relevant doc"]
}}
"""
    try:
        resp = qe.query(prompt)
        json_match = re.search(r'\{.*\}', str(resp), re.DOTALL)
        return json.loads(json_match.group()) if json_match else {}
    except Exception as e:
        logger.warning(f"Reasoning agent failed: {e}")
        return {"explanation": "Analysis unavailable"}