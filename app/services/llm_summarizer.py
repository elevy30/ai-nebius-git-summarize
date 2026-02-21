"""LLM-based repository summarizer using OpenAI API."""

import json
from openai import AsyncOpenAI, APIError, APITimeoutError
from app.services.github_client import RepoData
from app.config import Settings, get_settings


SYSTEM_PROMPT = """You are a senior software engineer analyzing a GitHub repository.
You will be given: repository metadata, its directory tree, and contents of key files.

Respond with a JSON object containing exactly these fields:
- "summary": A 2-4 paragraph description of what this project does, its purpose, and how it works at a high level.
- "technologies": A list of programming languages, frameworks, libraries, and tools used in this project.
- "structure": A description of how the project is organized, its main directories, and the role of key files.

Respond ONLY with the JSON object. Do not wrap it in markdown code fences or add any text outside the JSON."""


class SummarizerError(Exception):
    """Error during LLM summarization."""

    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class Summarizer:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _get_client(self) -> AsyncOpenAI:
        if not self.settings.openai_api_key:
            raise SummarizerError(
                "Server misconfiguration: LLM API key not set",
                status_code=500,
            )
        return AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_request_timeout,
        )

    def build_user_prompt(self, repo_data: RepoData) -> str:
        """Build the user prompt from repo data."""
        sections = []

        # Metadata header
        sections.append(f"# Repository: {repo_data.owner}/{repo_data.repo}")
        if repo_data.description:
            sections.append(f"# Description: {repo_data.description}")
        sections.append(
            f"# Stars: {repo_data.stars} | Forks: {repo_data.forks} "
            f"| Language: {repo_data.language}"
        )
        sections.append("")

        # Directory tree
        sections.append("## Directory Tree")
        sections.append("```")
        sections.append(repo_data.directory_tree)
        sections.append("```")
        sections.append("")

        # File contents
        sections.append("## File Contents")
        for path, content in repo_data.file_contents.items():
            sections.append(f"\n### {path}")
            sections.append("```")
            sections.append(content)
            sections.append("```")

        return "\n".join(sections)

    async def summarize(self, repo_data: RepoData) -> dict:
        """Generate a summary of the repository using OpenAI."""
        client = self._get_client()
        user_prompt = self.build_user_prompt(repo_data)

        try:
            response = await client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
        except APITimeoutError:
            raise SummarizerError(
                "LLM request timed out. Please try again.",
                status_code=504,
            )
        except APIError as e:
            raise SummarizerError(
                f"LLM summarization failed: {str(e)}",
                status_code=502,
            )

        if not response.choices:
            raise SummarizerError("LLM returned no choices", status_code=502)

        raw_content = response.choices[0].message.content
        if not raw_content:
            raise SummarizerError("LLM returned empty response", status_code=502)

        # Strip markdown fences if the LLM added them
        content = raw_content.strip()
        if content.startswith("```"):
            # Remove first line (```json or ```)
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            raise SummarizerError(
                "LLM returned malformed response. Please try again.",
                status_code=502,
            )

        # Validate required fields
        required = {"summary", "technologies", "structure"}
        missing = required - set(result.keys())
        if missing:
            raise SummarizerError(
                f"LLM response missing fields: {missing}",
                status_code=502,
            )

        return {
            "summary": str(result["summary"]),
            "technologies": list(result["technologies"]),
            "structure": str(result["structure"]),
        }
