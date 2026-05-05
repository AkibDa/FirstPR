import json
import re
import logging
from typing import List
from pydantic import BaseModel, Field

from llama_index.llms.ollama import Ollama
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings, PromptTemplate, Document
from llama_index.core import VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser

logger = logging.getLogger(__name__)

repo_cache: dict = {}

Settings.embed_model = HuggingFaceEmbedding(
  model_name="BAAI/bge-base-en-v1.5"
)

Settings.llm = Ollama(
  model="llama3.2:3b",
  base_url="http://localhost:11434",
  request_timeout=600.0,
  context_window=8192
)

class CodeExplanation(BaseModel):
  explanation: str = Field(description="Plain English explanation of what the code does.")
  logic_trace: List[str] = Field(description="Step-by-step logic trace of the files.")
  contribution_path: List[dict] = Field(description="Actionable steps for the user.")

def build_query_engine(content: str, repo_name: str):
  docs = []

  parts = re.split(r"================================================\n(?:File|FILE|file):\s*", content)

  for part in parts:
    if not part.strip() or "Directory structure:" in part:
      continue

    subparts = part.split("\n================================================\n", 1)
    if len(subparts) == 2:
      file_path = subparts[0].strip()
      code_text = subparts[1].strip()
      docs.append(Document(text=code_text, metadata={"file_path": file_path}))

  node_parser = MarkdownNodeParser()
  index = VectorStoreIndex.from_documents(
    documents=docs,
    transformations=[node_parser],
    show_progress=False,
  )
  return index.as_query_engine(streaming=False, similarity_top_k=5)


def extract_json(text: str) -> dict:
  try:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
      return json.loads(match.group())
    return {}
  except Exception as e:
    logger.warning(f"JSON parsing error: {e}")
    return {}


def run_issue_analyzer(tree: str, issue_full: str) -> dict:
  prompt = f"""
You are an expert open-source contributor mentor. Analyze the following GitHub issue and return a structured JSON response.

Repository structure:
{tree[:3000]}

Issue:
{issue_full}

Return ONLY valid JSON (no markdown) with this structure:
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
    resp = Settings.llm.complete(prompt)
    return extract_json(str(resp))
  except Exception as e:
    logger.warning(f"Issue analysis failed: {e}")
    return {}

def run_retrieval_agent(qe, issue_full: str) -> dict:
  try:
    nodes = qe.retriever.retrieve(issue_full)
    relevant_files = []
    seen = set()

    for node in nodes:
      path = node.metadata.get("file_path")
      if path and path not in seen:
        seen.add(path)
        relevant_files.append({
          "path": path,
          "relevance": "high",
          "reason": f"Semantic match score: {node.score:.2f}" if node.score else "Semantic match"
        })

    return {
      "relevant_files": relevant_files,
      "key_functions": [],
      "search_keywords": []
    }
  except Exception as e:
    logger.warning(f"Retrieval agent failed: {e}")
    return {}

def run_reasoning_agent(tree: str, retrieved_files: List[str], repo_content: str, issue_full: str) -> dict:
  code_context = ""

  parts = re.split(r"================================================\n(?:File|FILE|file):\s*", repo_content)

  for part in parts:
    subparts = part.split("\n================================================\n", 1)
    if len(subparts) == 2:
      file_path = subparts[0].strip()
      if file_path in retrieved_files:
        code_context += f"\n--- File: {file_path} ---\n{subparts[1].strip()[:4000]}\n"

  prompt_str = f"""
You are an expert code mentor helping a beginner open-source contributor solve a GitHub issue.

Repository tree:
{tree[:2000]}

Issue:
{issue_full}

Relevant Source Code:
{code_context}

Provide a clear, actionable contribution guide. Return ONLY valid JSON.
"""
  prompt_tmpl = PromptTemplate(prompt_str)

  try:
    response = Settings.llm.structured_predict(
      CodeExplanation,
      prompt=prompt_tmpl
    )
    return response.dict()
  except Exception as e:
    logger.error(f"Reasoning agent error: {str(e)}")
    return {"explanation": f"Failed to generate explanation from local model: {str(e)}"}
