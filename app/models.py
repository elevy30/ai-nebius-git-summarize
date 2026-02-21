from pydantic import BaseModel, field_validator
import re


class SummarizeRequest(BaseModel):
    github_url: str

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        pattern = r"^https?://github\.com/[\w.\-]+/[\w.\-]+/?$"
        if not re.match(pattern, v):
            raise ValueError(
                "Invalid GitHub URL. Expected format: https://github.com/{owner}/{repo}"
            )
        return v.rstrip("/")


class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
