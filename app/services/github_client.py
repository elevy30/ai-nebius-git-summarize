"""GitHub API client for fetching repository data."""

import httpx
from dataclasses import dataclass, field
from app.utils.file_filter import rank_and_select_files, should_exclude_path
from app.config import Settings, get_settings


@dataclass
class RepoData:
    owner: str
    repo: str
    description: str
    stars: int
    forks: int
    language: str
    default_branch: str
    directory_tree: str
    file_contents: dict[str, str] = field(default_factory=dict)


class GitHubClientError(Exception):
    """Base error for GitHub client operations."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class GitHubClient:
    GITHUB_API_BASE = "https://api.github.com"
    RAW_CONTENT_BASE = "https://raw.githubusercontent.com"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def parse_github_url(url: str) -> tuple[str, str]:
        """Extract owner and repo from a GitHub URL."""
        url = url.rstrip("/")
        parts = url.split("/")
        # URL format: https://github.com/{owner}/{repo}
        owner = parts[-2]
        repo = parts[-1]
        return owner, repo

    @staticmethod
    def build_directory_tree(paths: list[str]) -> str:
        """Build a text representation of the directory tree."""
        if not paths:
            return ""

        seen_dirs: set[str] = set()
        result_lines: list[str] = []
        for path in sorted(paths):
            parts = path.split("/")
            # Add parent directories if not seen
            for i in range(len(parts) - 1):
                dir_path = "/".join(parts[: i + 1])
                if dir_path not in seen_dirs:
                    seen_dirs.add(dir_path)
                    indent = "  " * i
                    result_lines.append(f"{indent}{parts[i]}/")
            # Add the file itself
            indent = "  " * (len(parts) - 1)
            result_lines.append(f"{indent}{parts[-1]}")

        return "\n".join(result_lines)

    async def fetch_repo_data(
        self, owner: str, repo: str
    ) -> RepoData:
        """Fetch repository metadata, tree, and key file contents."""
        timeout = httpx.Timeout(self.settings.github_request_timeout)

        async with httpx.AsyncClient(timeout=timeout) as client:
            # 1. Fetch repo metadata
            repo_url = f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}"
            repo_resp = await client.get(
                repo_url, headers={"Accept": "application/vnd.github.v3+json"}
            )

            if repo_resp.status_code == 404:
                raise GitHubClientError(
                    f"Repository not found: {owner}/{repo}", status_code=404
                )
            if repo_resp.status_code == 403:
                raise GitHubClientError(
                    "GitHub API rate limit exceeded. Try again later.",
                    status_code=429,
                )
            if repo_resp.status_code != 200:
                raise GitHubClientError(
                    "Failed to fetch repository data from GitHub",
                    status_code=502,
                )

            try:
                repo_info = repo_resp.json()
            except ValueError:
                raise GitHubClientError(
                    "Failed to parse GitHub API response",
                    status_code=502,
                )
            default_branch = repo_info.get("default_branch", "main")

            # 2. Fetch full tree
            tree_url = (
                f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}"
                f"/git/trees/{default_branch}?recursive=1"
            )
            tree_resp = await client.get(
                tree_url, headers={"Accept": "application/vnd.github.v3+json"}
            )

            if tree_resp.status_code != 200:
                raise GitHubClientError(
                    "Failed to fetch repository tree from GitHub",
                    status_code=502,
                )

            try:
                tree_data = tree_resp.json()
            except ValueError:
                raise GitHubClientError(
                    "Failed to parse GitHub tree response",
                    status_code=502,
                )
            tree_items = tree_data.get("tree", [])

            # Filter to blobs (files) only
            file_items = [
                {"path": item["path"], "size": item.get("size", 0)}
                for item in tree_items
                if item.get("type") == "blob"
            ]

            # All paths (for directory tree display)
            all_paths = [
                item["path"]
                for item in tree_items
                if not should_exclude_path(item["path"])
            ]

            # Build directory tree string
            directory_tree = self.build_directory_tree(all_paths)

            # 3. Rank and select files to fetch
            # Reserve some budget for tree + metadata
            tree_chars = len(directory_tree)
            content_budget = self.settings.max_content_chars - tree_chars - 2000
            content_budget = max(content_budget, 10000)  # At least 10k chars

            selected_files = rank_and_select_files(
                file_items, max_chars=content_budget
            )

            # 4. Fetch file contents from raw.githubusercontent.com
            file_contents: dict[str, str] = {}
            failed_downloads: list[str] = []
            for file_info in selected_files:
                path = file_info["path"]
                raw_url = (
                    f"{self.RAW_CONTENT_BASE}/{owner}/{repo}"
                    f"/{default_branch}/{path}"
                )
                try:
                    content_resp = await client.get(raw_url)
                    if content_resp.status_code == 200:
                        text = content_resp.text
                        # Truncate very large individual files
                        if len(text) > 50_000:
                            text = text[:50_000] + "\n\n... [truncated]"
                        file_contents[path] = text
                    else:
                        failed_downloads.append(path)
                except (httpx.TimeoutException, httpx.HTTPError):
                    failed_downloads.append(path)

            if not file_contents and not directory_tree:
                raise GitHubClientError(
                    "Repository appears empty or has no analyzable files",
                    status_code=422,
                )

            return RepoData(
                owner=owner,
                repo=repo,
                description=repo_info.get("description", "") or "",
                stars=repo_info.get("stargazers_count", 0),
                forks=repo_info.get("forks_count", 0),
                language=repo_info.get("language", "") or "",
                default_branch=default_branch,
                directory_tree=directory_tree,
                file_contents=file_contents,
            )
