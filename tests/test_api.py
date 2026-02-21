from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.services.github_client import RepoData

client = TestClient(app)


class TestHealthCheck:
    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSummarizeEndpointValidation:
    def test_invalid_url_returns_422(self):
        response = client.post("/summarize", json={"github_url": "not-a-url"})
        assert response.status_code == 422

    def test_missing_url_returns_422(self):
        response = client.post("/summarize", json={})
        assert response.status_code == 422


class TestSummarizeEndpointIntegration:
    """Test the full /summarize flow with mocked external services."""

    def test_full_flow_success(self):
        mock_repo_data = RepoData(
            owner="psf",
            repo="requests",
            description="Python HTTP library",
            stars=50000,
            forks=9000,
            language="Python",
            default_branch="main",
            directory_tree="README.md\nsrc/\n  main.py",
            file_contents={"README.md": "# Requests"},
        )

        mock_llm_result = {
            "summary": "Requests is an HTTP library.",
            "technologies": ["Python"],
            "structure": "Simple layout.",
        }

        with patch(
            "app.routers.summarize.GitHubClient"
        ) as MockGHClient, patch(
            "app.routers.summarize.Summarizer"
        ) as MockSummarizer:
            mock_gh = MockGHClient.return_value
            mock_gh.parse_github_url.return_value = ("psf", "requests")
            mock_gh.fetch_repo_data = AsyncMock(return_value=mock_repo_data)

            mock_sum = MockSummarizer.return_value
            mock_sum.summarize = AsyncMock(return_value=mock_llm_result)

            response = client.post(
                "/summarize",
                json={"github_url": "https://github.com/psf/requests"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Requests is an HTTP library."
        assert data["technologies"] == ["Python"]
        assert data["structure"] == "Simple layout."

    def test_github_404_returns_404(self):
        from app.services.github_client import GitHubClientError

        with patch("app.routers.summarize.GitHubClient") as MockGHClient:
            mock_gh = MockGHClient.return_value
            mock_gh.parse_github_url.return_value = ("foo", "nonexistent")
            mock_gh.fetch_repo_data = AsyncMock(
                side_effect=GitHubClientError(
                    "Repository not found: foo/nonexistent", status_code=404
                )
            )

            response = client.post(
                "/summarize",
                json={"github_url": "https://github.com/foo/nonexistent"},
            )

        assert response.status_code == 404
        assert "not found" in response.json()["message"]
