from pydantic import BaseModel
from typing import Optional

class AnalyzeRequest(BaseModel):
    repo_url: str
    issue_text: str
    issue_title: Optional[str] = ""

class RepoLoadRequest(BaseModel):
    repo_url: str