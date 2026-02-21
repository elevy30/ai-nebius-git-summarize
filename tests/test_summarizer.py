import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.summarizer import Summarizer, SummarizerError
from app.services.github_client import RepoData


@pytest.fixture
def sample_repo_data():
    return RepoData(
        owner="psf",
        repo="requests",
        description="Python HTTP library",
        stars=50000,
        forks=9000,
        language="Python",
        default_branch="main",
        directory_tree="README.md\nsrc/\n  main.py",
        file_contents={
            "README.md": "# Requests\nHTTP for Humans",
            "src/main.py": "import http\n\ndef get(url): ...",
        },
    )


class TestBuildPrompt:
    def test_prompt_contains_repo_name(self, sample_repo_data):
        summarizer = Summarizer()
        prompt = summarizer.build_user_prompt(sample_repo_data)
        assert "psf/requests" in prompt

    def test_prompt_contains_tree(self, sample_repo_data):
        summarizer = Summarizer()
        prompt = summarizer.build_user_prompt(sample_repo_data)
        assert "README.md" in prompt
        assert "src/" in prompt

    def test_prompt_contains_file_contents(self, sample_repo_data):
        summarizer = Summarizer()
        prompt = summarizer.build_user_prompt(sample_repo_data)
        assert "HTTP for Humans" in prompt

    def test_prompt_contains_metadata(self, sample_repo_data):
        summarizer = Summarizer()
        prompt = summarizer.build_user_prompt(sample_repo_data)
        assert "50000" in prompt or "50,000" in prompt


@pytest.mark.asyncio
class TestSummarize:
    async def test_successful_summarization(self, sample_repo_data):
        summarizer = Summarizer()

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        {
                            "summary": "Requests is a Python HTTP library.",
                            "technologies": ["Python", "HTTP"],
                            "structure": "Simple structure with src/.",
                        }
                    )
                )
            )
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(summarizer, "_get_client", return_value=mock_client):
            result = await summarizer.summarize(sample_repo_data)

        assert result["summary"] == "Requests is a Python HTTP library."
        assert "Python" in result["technologies"]
        assert "structure" in result

    async def test_handles_malformed_json(self, sample_repo_data):
        summarizer = Summarizer()

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Not valid JSON"))
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(summarizer, "_get_client", return_value=mock_client):
            with pytest.raises(SummarizerError):
                await summarizer.summarize(sample_repo_data)
