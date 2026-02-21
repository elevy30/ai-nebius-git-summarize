import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    max_content_chars: int = 100_000  # ~25k tokens
    max_file_size_bytes: int = 100_000  # Skip files > 100KB
    github_request_timeout: float = 30.0
    openai_request_timeout: float = 120.0


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
