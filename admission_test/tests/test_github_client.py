import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.github_client import GitHubClient, RepoData


class TestParseGithubUrl:
    def test_standard_url(self):
        client = GitHubClient()
        owner, repo = client.parse_github_url("https://github.com/psf/requests")
        assert owner == "psf"
        assert repo == "requests"

    def test_trailing_slash(self):
        client = GitHubClient()
        owner, repo = client.parse_github_url("https://github.com/psf/requests/")
        assert owner == "psf"
        assert repo == "requests"


class TestBuildDirectoryTree:
    def test_simple_tree(self):
        client = GitHubClient()
        paths = ["README.md", "src/main.py", "src/utils.py", "tests/test_main.py"]
        tree = client.build_directory_tree(paths)
        assert "README.md" in tree
        assert "src/" in tree
        assert "  main.py" in tree

    def test_empty_paths(self):
        client = GitHubClient()
        tree = client.build_directory_tree([])
        assert tree == ""


@pytest.mark.asyncio
class TestFetchRepoData:
    async def test_fetch_repo_success(self):
        client = GitHubClient()

        mock_repo_response = MagicMock()
        mock_repo_response.status_code = 200
        mock_repo_response.json.return_value = {
            "default_branch": "main",
            "description": "Python HTTP library",
            "stargazers_count": 50000,
            "forks_count": 9000,
            "language": "Python",
        }

        mock_tree_response = MagicMock()
        mock_tree_response.status_code = 200
        mock_tree_response.json.return_value = {
            "tree": [
                {"path": "README.md", "type": "blob", "size": 5000},
                {"path": "src", "type": "tree"},
                {"path": "src/main.py", "type": "blob", "size": 2000},
            ],
            "truncated": False,
        }

        mock_content_readme = MagicMock()
        mock_content_readme.status_code = 200
        mock_content_readme.text = "# Requests\nHTTP library"

        mock_content_main = MagicMock()
        mock_content_main.status_code = 200
        mock_content_main.text = "import http\n\ndef get(url): ..."

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                mock_repo_response,
                mock_tree_response,
                mock_content_readme,
                mock_content_main,
            ]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            repo_data = await client.fetch_repo_data("psf", "requests")

        assert repo_data.owner == "psf"
        assert repo_data.repo == "requests"
        assert repo_data.description == "Python HTTP library"
        assert len(repo_data.directory_tree) > 0
