import pytest
from app.models import SummarizeRequest, SummarizeResponse


class TestSummarizeRequest:
    def test_valid_url(self):
        req = SummarizeRequest(github_url="https://github.com/psf/requests")
        assert req.github_url == "https://github.com/psf/requests"

    def test_valid_url_trailing_slash(self):
        req = SummarizeRequest(github_url="https://github.com/psf/requests/")
        assert req.github_url == "https://github.com/psf/requests"

    def test_valid_url_http(self):
        req = SummarizeRequest(github_url="http://github.com/psf/requests")
        assert req.github_url == "http://github.com/psf/requests"

    def test_invalid_url_not_github(self):
        with pytest.raises(ValueError):
            SummarizeRequest(github_url="https://gitlab.com/foo/bar")

    def test_invalid_url_no_repo(self):
        with pytest.raises(ValueError):
            SummarizeRequest(github_url="https://github.com/psf")

    def test_invalid_url_random(self):
        with pytest.raises(ValueError):
            SummarizeRequest(github_url="not-a-url")

    def test_invalid_url_with_subpath(self):
        with pytest.raises(ValueError):
            SummarizeRequest(github_url="https://github.com/psf/requests/tree/main")


class TestSummarizeResponse:
    def test_creation(self):
        resp = SummarizeResponse(
            summary="A library",
            technologies=["Python"],
            structure="Simple layout",
        )
        assert resp.summary == "A library"
        assert resp.technologies == ["Python"]
