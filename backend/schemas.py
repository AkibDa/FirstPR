from pydantic import BaseModel, Field, model_validator
from typing import Optional, List

class RepoLoadRequest(BaseModel):
    repo_url: str

class RepoQARequest(BaseModel):
    repo_url: str
    question: str

class AnalyzeRequest(BaseModel):
    repo_url: str

    issue_text: Optional[str] = None
    issue_title: Optional[str] = ""

    issue_url: Optional[str] = None

    @model_validator(mode="after")
    def require_issue_source(self) -> "AnalyzeRequest":
        if not self.issue_text and not self.issue_url:
            raise ValueError(
                "Provide either 'issue_text' or 'issue_url' (a GitHub issue URL)."
            )
        return self

class RelevantFile(BaseModel):
    path: str
    relevance: str = "high"
    reason: str
    functions: List[str] = Field(default_factory=list)
    classes: List[str] = Field(default_factory=list)
    role: Optional[str] = None

class ContributionStep(BaseModel):
    step: int
    title: str
    description: str
    files_involved: List[str] = Field(default_factory=list)

class PatchHunk(BaseModel):
    file_path: str
    diff: str

class CodeExplanation(BaseModel):
    where_to_start: str = Field(
        description="The very first file or function a beginner should open."
    )
    what_to_read_first: List[str] = Field(
        description="Ordered list of files/sections to read before touching code."
    )
    explanation: str = Field(
        description="Plain-English explanation of what the relevant code does."
    )
    logic_trace: List[str] = Field(
        description="Step-by-step reasoning trace across connected files."
    )
    contribution_path: List[ContributionStep] = Field(
        description="Actionable, ordered steps for the contributor."
    )
    common_mistakes: List[str] = Field(
        description="Pitfalls a beginner is likely to hit on this issue."
    )
    dependency_chain: List[str] = Field(
        default_factory=list,
        description="Import/call chain leading to the affected code.",
    )
    suggested_patch: Optional[PatchHunk] = Field(
        default=None,
        description="Optional unified diff with a concrete code fix.",
    )
    