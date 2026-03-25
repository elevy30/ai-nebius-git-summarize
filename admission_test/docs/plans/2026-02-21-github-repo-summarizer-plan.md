# GitHub Repo Summarizer API - Implementation Plan

> **For Claude:** REQUIRED: Follow this plan task-by-task using TDD.
> **Design:** Self-contained in this file (no separate design doc).

**Goal:** Build a FastAPI service with a `POST /summarize` endpoint that takes a GitHub repo URL, fetches repo contents intelligently, and returns an LLM-generated summary including a prose summary, technologies list, and structure description.

**Architecture:** Single FastAPI application with three layers: (1) API layer (FastAPI router + Pydantic models), (2) GitHub client layer (httpx-based, fetches repo tree + file contents via GitHub REST API), (3) LLM summarizer layer (OpenAI client, prompt construction, response parsing). The GitHub client builds a "context bundle" of the most informative files within a token budget, then the summarizer sends that bundle to OpenAI for analysis.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, httpx, openai, pydantic (bundled with FastAPI)

**Prerequisites:** Poetry environment with dependencies installed, `OPENAI_API_KEY` in `.env`

---

## Relevant Codebase Files

### Configuration Files
- `/Users/eyal.levy/dev/git/elevy30/nebius/pyproject.toml` - Dependencies: fastapi, uvicorn, httpx, openai
- `/Users/eyal.levy/dev/git/elevy30/nebius/.env` - Contains OPENAI_API_KEY

### Patterns to Follow
- Fresh project, no existing patterns. Establish conventions here.

---

## Architecture Design

### System Context

```
User (HTTP Client)
    |
    | POST /summarize {"github_url": "..."}
    v
+------------------------------------------+
|            FastAPI Application            |
|  +----------+  +---------+  +----------+ |
|  | API Layer|->| GitHub  |->| LLM      | |
|  | (router) |  | Client  |  | Summarizer||
|  +----------+  +---------+  +----------+ |
+------------------------------------------+
       |               |             |
       v               v             v
   Pydantic      GitHub REST     OpenAI API
   Models        API (v3)        (chat completions)
```

### System Flow

```
1. POST /summarize arrives with {"github_url": "https://github.com/owner/repo"}
2. API layer validates URL format (must be github.com/{owner}/{repo})
3. GitHub client extracts owner/repo from URL
4. GitHub client calls GET /repos/{owner}/{repo} for repo metadata
5. GitHub client calls GET /repos/{owner}/{repo}/git/trees/HEAD?recursive=1 for full tree
6. GitHub client filters tree: skip binaries, lock files, vendor dirs, etc.
7. GitHub client ranks remaining files by priority (README > config > source)
8. GitHub client fetches top-priority files via raw.githubusercontent.com until token budget is reached
9. LLM summarizer builds a prompt with: repo metadata, directory tree, file contents
10. LLM summarizer calls OpenAI chat completions with structured output request
11. LLM summarizer parses response into summary, technologies, structure
12. API layer returns JSON response
```

### File Structure to Create

```
app/
  __init__.py           # Empty, makes app a package
  main.py               # FastAPI app instance, mounts router, loads .env
  config.py             # Settings (OpenAI key, model, token budget)
  models.py             # Pydantic request/response models
  routers/
    __init__.py
    summarize.py        # POST /summarize endpoint
  services/
    __init__.py
    github_client.py    # Fetches repo tree + file contents from GitHub API
    summarizer.py       # Builds prompt, calls OpenAI, parses response
  utils/
    __init__.py
    file_filter.py      # File filtering logic (skip binaries, rank by priority)
tests/
  __init__.py
  test_models.py        # Test Pydantic models
  test_file_filter.py   # Test file filtering/ranking logic
  test_github_client.py # Test GitHub client (mocked)
  test_summarizer.py    # Test summarizer (mocked)
  test_api.py           # Integration test for /summarize endpoint
README.md               # Project documentation
```

---

## Key Design Decisions

### ADR 1: GitHub API Strategy -- Tree API + Raw Content

**Context:** Need to fetch repo contents efficiently within 60 req/hour unauthenticated limit.

**Decision:** Use the Git Trees API (`GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1`) to get the full directory tree in a single request, then fetch individual file contents via `raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}` (which does NOT count against the GitHub API rate limit).

**Consequences:**
- Positive: Full tree in 1 API call; raw content fetches are free from rate limits
- Positive: Can filter/rank files before fetching any content
- Negative: Need to resolve default branch first (1 more API call for repo metadata)
- Alternatives: Contents API (`/repos/{owner}/{repo}/contents/`) -- paginated, needs recursion, wastes rate limit

**Total GitHub API calls per request: 2** (repo metadata + tree). Raw content fetches are unlimited.

### ADR 2: File Priority Ranking Strategy

**Context:** Repos can contain thousands of files. Must select the most informative subset.

**Decision:** Three-tier priority system with token budget allocation:

| Priority | File Types | Budget Share | Rationale |
|----------|-----------|--------------|-----------|
| **Tier 1 (Must-have)** | README.md/README.rst, directory tree listing | 30% | Highest signal-to-noise for understanding a repo |
| **Tier 2 (Config/Meta)** | package.json, pyproject.toml, Cargo.toml, go.mod, Makefile, Dockerfile, docker-compose.yml, .github/workflows/*.yml, setup.py, setup.cfg, requirements.txt, Gemfile, pom.xml, build.gradle | 20% | Reveal tech stack, dependencies, build process |
| **Tier 3 (Key Source)** | Entry points (main.py, index.ts, app.py, etc.), files in src/ root, models/schemas, short source files sorted by size ascending | 50% | Actual code gives the LLM concrete understanding |

Within each tier, files are fetched in order until that tier's token budget is exhausted. Remaining budget rolls forward to the next tier.

### ADR 3: File Filtering -- Exclusion Lists

**Context:** Must skip binary files, generated files, vendor dirs, lock files.

**Decision:** Two exclusion mechanisms:

1. **Directory exclusion** (skip entire subtrees):
   ```
   node_modules/, vendor/, .git/, dist/, build/, __pycache__/,
   .venv/, venv/, .idea/, .vscode/, .tox/, .mypy_cache/,
   .pytest_cache/, .next/, .nuxt/, target/, bin/, obj/,
   coverage/, .coverage/, htmlcov/, .eggs/, *.egg-info/
   ```

2. **File extension exclusion** (skip individual files):
   ```
   Binary: .png, .jpg, .jpeg, .gif, .ico, .svg, .woff, .woff2,
           .ttf, .eot, .mp3, .mp4, .zip, .tar, .gz, .pdf,
           .exe, .dll, .so, .dylib, .pyc, .pyo, .class, .o
   Generated/Lock: package-lock.json, yarn.lock, poetry.lock,
                   Cargo.lock, Gemfile.lock, composer.lock,
                   go.sum, pnpm-lock.yaml, shrinkwrap.json
   Data: .min.js, .min.css, .map, .chunk.js
   ```

3. **Size exclusion:** Skip files > 100KB (likely generated/data).

### ADR 4: Token Budget Management

**Context:** OpenAI models have context limits. Must fit prompt within limits.

**Decision:** Use a character-based budget as a proxy for tokens (1 token ~= 4 chars). Default model: `gpt-4o-mini` (128k context). Reserve 2,000 tokens for the system prompt and response, leaving ~120,000 tokens (~480,000 chars) for repo content. Configure via `config.py` so it can be tuned.

Practical default: **100,000 characters** for repo content (conservative, works for all models).

### ADR 5: LLM Prompt Strategy

**Context:** Need structured output (summary, technologies, structure).

**Decision:** Use a system prompt that instructs the LLM to act as a senior developer analyzing a repository, with a user prompt containing the repo data. Request JSON-formatted response.

System prompt:
```
You are a senior software engineer analyzing a GitHub repository.
You will be given: repository metadata, its directory tree, and
contents of key files.

Respond with a JSON object containing exactly these fields:
- "summary": A 2-4 paragraph description of what this project does,
  its purpose, and how it works at a high level.
- "technologies": A list of programming languages, frameworks,
  libraries, and tools used in this project.
- "structure": A description of how the project is organized,
  its main directories, and the role of key files.

Respond ONLY with the JSON object, no markdown fences or extra text.
```

User prompt template:
```
# Repository: {owner}/{repo}
# Description: {description}
# Stars: {stars} | Forks: {forks} | Language: {language}

## Directory Tree
{tree}

## File Contents

### {file_path_1}
```
{content_1}
```

### {file_path_2}
```
{content_2}
```
...
```

### ADR 6: Error Handling Strategy

**Context:** Multiple failure points: invalid URL, GitHub 404, rate limiting, OpenAI errors.

**Decision:** Map each failure to a specific HTTP status and message:

| Failure | HTTP Status | Error Message |
|---------|-------------|---------------|
| Invalid URL format | 400 | "Invalid GitHub URL. Expected: https://github.com/{owner}/{repo}" |
| GitHub repo not found | 404 | "Repository not found: {owner}/{repo}" |
| GitHub rate limited | 429 | "GitHub API rate limit exceeded. Try again later." |
| GitHub API error | 502 | "Failed to fetch repository data from GitHub" |
| Empty repo / no files | 422 | "Repository appears empty or has no analyzable files" |
| OpenAI API error | 502 | "LLM summarization failed. Please try again." |
| OpenAI timeout | 504 | "LLM request timed out. Please try again." |
| OPENAI_API_KEY not set | 500 | "Server misconfiguration: LLM API key not set" |

---

## Phase 1: Project Foundation (Exit Criteria: App starts, returns 200 on health check)

### Task 1: Create Config Module

**Files:**
- Create: `app/__init__.py`
- Create: `app/config.py`

**Step 1: Create empty `app/__init__.py`**

```python
# app/__init__.py
```

**Step 2: Create `app/config.py` with Settings class**

```python
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
```

**Step 3: Verify**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/python -c "from app.config import get_settings; s = get_settings(); print(s)"`
Expected: Settings dataclass printed, no import errors.

### Task 2: Create Pydantic Models

**Files:**
- Create: `app/models.py`

**Step 1: Create `app/models.py`**

```python
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
```

**Step 2: Write test**

Create `tests/__init__.py` and `tests/test_models.py`:

```python
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
```

**Step 3: Run tests**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/python -m pytest tests/test_models.py -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add app/__init__.py app/config.py app/models.py tests/__init__.py tests/test_models.py
git commit -m "feat: add config and Pydantic request/response models"
```

### Task 3: Create FastAPI App with Health Check

**Files:**
- Create: `app/main.py`
- Create: `app/routers/__init__.py`
- Create: `app/routers/summarize.py` (stub)

**Step 1: Create `app/main.py`**

```python
from fastapi import FastAPI
from app.routers import summarize

app = FastAPI(
    title="GitHub Repo Summarizer",
    description="Summarize GitHub repositories using LLM",
    version="0.1.0",
)

app.include_router(summarize.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

**Step 2: Create stub router `app/routers/summarize.py`**

```python
from fastapi import APIRouter
from app.models import SummarizeRequest, SummarizeResponse, ErrorResponse

router = APIRouter()


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def summarize_repo(request: SummarizeRequest):
    # Stub - will be implemented in Phase 3
    return SummarizeResponse(
        summary="Stub summary",
        technologies=["Stub"],
        structure="Stub structure",
    )
```

**Step 3: Create `app/routers/__init__.py`**

```python
# app/routers/__init__.py
```

**Step 4: Write integration test**

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

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

    def test_valid_url_returns_200(self):
        # Stub returns 200
        response = client.post(
            "/summarize", json={"github_url": "https://github.com/psf/requests"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "technologies" in data
        assert "structure" in data
```

**Step 5: Run all tests**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 6: Verify server starts**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && timeout 5 .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 || true`
Expected: Server starts, shows "Uvicorn running on http://0.0.0.0:8000".

**Step 7: Commit**

```bash
git add app/main.py app/routers/__init__.py app/routers/summarize.py tests/test_api.py
git commit -m "feat: add FastAPI app with health check and stubbed /summarize endpoint"
```

---

## Phase 2: File Filtering and Ranking (Exit Criteria: Filter logic unit-tested, correctly ranks files)

### Task 4: Create File Filter Module

**Files:**
- Create: `app/utils/__init__.py`
- Create: `app/utils/file_filter.py`
- Create: `tests/test_file_filter.py`

**Step 1: Write tests first**

Create `tests/test_file_filter.py`:

```python
import pytest
from app.utils.file_filter import (
    should_exclude_path,
    get_file_priority,
    rank_and_select_files,
    PRIORITY_TIER1,
    PRIORITY_TIER2,
    PRIORITY_TIER3,
    PRIORITY_SKIP,
)


class TestShouldExcludePath:
    def test_excludes_node_modules(self):
        assert should_exclude_path("node_modules/express/index.js") is True

    def test_excludes_vendor(self):
        assert should_exclude_path("vendor/autoload.php") is True

    def test_excludes_pycache(self):
        assert should_exclude_path("__pycache__/module.cpython-310.pyc") is True

    def test_excludes_dotgit(self):
        assert should_exclude_path(".git/config") is True

    def test_excludes_venv(self):
        assert should_exclude_path(".venv/lib/python3.10/site.py") is True

    def test_allows_src_files(self):
        assert should_exclude_path("src/main.py") is False

    def test_allows_root_files(self):
        assert should_exclude_path("README.md") is False

    def test_excludes_binary_extensions(self):
        assert should_exclude_path("images/logo.png") is True
        assert should_exclude_path("fonts/arial.woff2") is True

    def test_excludes_lock_files(self):
        assert should_exclude_path("package-lock.json") is True
        assert should_exclude_path("poetry.lock") is True
        assert should_exclude_path("yarn.lock") is True

    def test_excludes_min_files(self):
        assert should_exclude_path("dist/app.min.js") is True
        assert should_exclude_path("styles/main.min.css") is True


class TestGetFilePriority:
    def test_readme_is_tier1(self):
        assert get_file_priority("README.md") == PRIORITY_TIER1

    def test_readme_rst_is_tier1(self):
        assert get_file_priority("README.rst") == PRIORITY_TIER1

    def test_package_json_is_tier2(self):
        assert get_file_priority("package.json") == PRIORITY_TIER2

    def test_pyproject_toml_is_tier2(self):
        assert get_file_priority("pyproject.toml") == PRIORITY_TIER2

    def test_dockerfile_is_tier2(self):
        assert get_file_priority("Dockerfile") == PRIORITY_TIER2

    def test_github_workflow_is_tier2(self):
        assert get_file_priority(".github/workflows/ci.yml") == PRIORITY_TIER2

    def test_main_py_is_tier3(self):
        assert get_file_priority("main.py") == PRIORITY_TIER3

    def test_src_file_is_tier3(self):
        assert get_file_priority("src/app.py") == PRIORITY_TIER3

    def test_deep_nested_file_is_tier3(self):
        assert get_file_priority("src/utils/helpers/format.py") == PRIORITY_TIER3

    def test_test_files_deprioritized(self):
        p1 = get_file_priority("src/app.py")
        p2 = get_file_priority("tests/test_app.py")
        assert p2 > p1  # Higher number = lower priority


class TestRankAndSelectFiles:
    def test_selects_within_budget(self):
        files = [
            {"path": "README.md", "size": 500},
            {"path": "src/main.py", "size": 300},
            {"path": "src/utils.py", "size": 200},
        ]
        selected = rank_and_select_files(files, max_chars=900)
        paths = [f["path"] for f in selected]
        assert "README.md" in paths

    def test_respects_budget(self):
        files = [
            {"path": "README.md", "size": 600},
            {"path": "src/main.py", "size": 600},
        ]
        selected = rank_and_select_files(files, max_chars=700)
        assert len(selected) == 1

    def test_readme_selected_first(self):
        files = [
            {"path": "src/main.py", "size": 100},
            {"path": "README.md", "size": 100},
            {"path": "package.json", "size": 100},
        ]
        selected = rank_and_select_files(files, max_chars=10000)
        assert selected[0]["path"] == "README.md"

    def test_empty_list(self):
        selected = rank_and_select_files([], max_chars=10000)
        assert selected == []

    def test_skips_excluded_files(self):
        files = [
            {"path": "README.md", "size": 100},
            {"path": "node_modules/foo.js", "size": 100},
        ]
        selected = rank_and_select_files(files, max_chars=10000)
        paths = [f["path"] for f in selected]
        assert "node_modules/foo.js" not in paths
```

**Step 2: Implement `app/utils/__init__.py`**

```python
# app/utils/__init__.py
```

**Step 3: Implement `app/utils/file_filter.py`**

```python
"""File filtering and priority ranking for GitHub repository analysis."""

PRIORITY_TIER1 = 1   # README, top-level docs
PRIORITY_TIER2 = 2   # Config files, package manifests
PRIORITY_TIER3 = 3   # Source code files
PRIORITY_TIER4 = 4   # Test files, docs, examples
PRIORITY_SKIP = 99   # Should not be fetched

# Directories to completely skip
EXCLUDED_DIRS: set[str] = {
    "node_modules", "vendor", ".git", "dist", "build", "__pycache__",
    ".venv", "venv", "env", ".idea", ".vscode", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "target", "bin", "obj",
    "coverage", ".coverage", "htmlcov", ".eggs", ".gradle",
    ".terraform", ".serverless",
}

# File extensions to skip (binary/generated)
EXCLUDED_EXTENSIONS: set[str] = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp", ".webp",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Media
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    # Compiled
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".class", ".o",
    ".wasm",
    # Data
    ".sqlite", ".db",
    # Source maps
    ".map",
}

# Specific filenames to skip (lock files, generated)
EXCLUDED_FILENAMES: set[str] = {
    "package-lock.json", "yarn.lock", "poetry.lock", "Cargo.lock",
    "Gemfile.lock", "composer.lock", "go.sum", "pnpm-lock.yaml",
    "npm-shrinkwrap.json", ".DS_Store", "Thumbs.db",
}

# Tier 1: README and top-level docs (highest priority)
TIER1_FILENAMES: set[str] = {
    "README.md", "README.rst", "README.txt", "README",
}

# Tier 2: Config/manifest files
TIER2_FILENAMES: set[str] = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Makefile", "CMakeLists.txt", "Dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "requirements.txt", "Gemfile", "Pipfile",
    "tsconfig.json", "tox.ini", ".eslintrc.json", ".eslintrc.js",
    "webpack.config.js", "vite.config.ts", "vite.config.js",
    "next.config.js", "next.config.mjs",
}

# Tier 2: Directory patterns for config files
TIER2_DIR_PATTERNS: list[str] = [
    ".github/workflows/",
]

# Tier 3: Entry point filenames (higher priority within tier 3)
TIER3_ENTRY_POINTS: set[str] = {
    "main.py", "app.py", "index.ts", "index.js", "main.ts", "main.js",
    "server.py", "server.ts", "server.js", "main.go", "main.rs",
    "lib.rs", "mod.rs", "index.py",
}

# Source code extensions
SOURCE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".swift", ".scala", ".clj", ".ex", ".exs", ".hs", ".lua",
    ".r", ".R", ".jl", ".sh", ".bash", ".zsh", ".fish",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".html", ".css",
    ".scss", ".less", ".sql", ".graphql", ".proto", ".tf",
    ".md", ".rst", ".txt",
}


def should_exclude_path(path: str) -> bool:
    """Check if a file path should be excluded from analysis."""
    parts = path.split("/")

    # Check directory exclusions
    for part in parts[:-1]:  # All parts except filename
        if part in EXCLUDED_DIRS:
            return True

    filename = parts[-1]

    # Check excluded filenames
    if filename in EXCLUDED_FILENAMES:
        return True

    # Check excluded extensions
    dot_idx = filename.rfind(".")
    if dot_idx != -1:
        ext = filename[dot_idx:].lower()
        if ext in EXCLUDED_EXTENSIONS:
            return True

    # Check minified files
    if filename.endswith(".min.js") or filename.endswith(".min.css"):
        return True

    # Check chunk files
    if ".chunk." in filename:
        return True

    return False


def get_file_priority(path: str) -> int:
    """Return priority tier for a file (lower number = higher priority)."""
    parts = path.split("/")
    filename = parts[-1]

    # Tier 1: README
    if filename.upper().startswith("README"):
        return PRIORITY_TIER1

    # Tier 2: Config/manifest files
    if filename in TIER2_FILENAMES:
        return PRIORITY_TIER2

    # Tier 2: GitHub workflows and similar config dirs
    for pattern in TIER2_DIR_PATTERNS:
        if path.startswith(pattern):
            return PRIORITY_TIER2

    # Check if it's a source file at all
    dot_idx = filename.rfind(".")
    ext = filename[dot_idx:].lower() if dot_idx != -1 else ""

    if ext not in SOURCE_EXTENSIONS and filename not in TIER3_ENTRY_POINTS:
        return PRIORITY_SKIP

    # Tier 4: Test files (lower priority than regular source)
    lower_path = path.lower()
    if (
        "/test" in lower_path
        or "/tests" in lower_path
        or "/spec" in lower_path
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith(".test.js")
        or filename.endswith(".test.ts")
        or filename.endswith(".spec.js")
        or filename.endswith(".spec.ts")
    ):
        return PRIORITY_TIER4

    # Tier 3: Entry points (slightly higher within tier 3)
    # Tier 3: Regular source files
    return PRIORITY_TIER3


def _sort_key(file_info: dict) -> tuple:
    """Sort key: (priority, depth, size). Shallower and smaller files first."""
    path = file_info["path"]
    priority = get_file_priority(path)
    depth = path.count("/")
    size = file_info.get("size", 0)
    # Entry points get a slight boost within their tier
    filename = path.split("/")[-1]
    is_entry = 0 if filename in TIER3_ENTRY_POINTS else 1
    return (priority, is_entry, depth, size)


def rank_and_select_files(
    files: list[dict], max_chars: int
) -> list[dict]:
    """Rank files by priority and select within character budget.

    Args:
        files: List of dicts with "path" and "size" keys.
        max_chars: Maximum total characters to select.

    Returns:
        Ordered list of file dicts to fetch, within budget.
    """
    # Filter out excluded files
    eligible = [f for f in files if not should_exclude_path(f["path"])]

    # Filter out files with non-source extensions that aren't config
    eligible = [f for f in eligible if get_file_priority(f["path"]) != PRIORITY_SKIP]

    # Sort by priority
    eligible.sort(key=_sort_key)

    # Select within budget
    selected = []
    total_chars = 0
    for f in eligible:
        estimated_chars = f.get("size", 0)
        if total_chars + estimated_chars > max_chars and selected:
            continue  # Skip but keep trying smaller files
        selected.append(f)
        total_chars += estimated_chars

    return selected
```

**Step 4: Run tests**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/python -m pytest tests/test_file_filter.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add app/utils/__init__.py app/utils/file_filter.py tests/test_file_filter.py
git commit -m "feat: add file filtering and priority ranking logic"
```

---

## Phase 3: GitHub Client (Exit Criteria: Can fetch repo metadata, tree, and file contents)

### Task 5: Create GitHub Client Service

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/github_client.py`
- Create: `tests/test_github_client.py`

**Step 1: Write tests first**

Create `tests/test_github_client.py`:

```python
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

        mock_content_response = MagicMock()
        mock_content_response.status_code = 200
        mock_content_response.text = "# Requests\nHTTP library"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[mock_repo_response, mock_tree_response, mock_content_response]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            repo_data = await client.fetch_repo_data("psf", "requests")

        assert repo_data.owner == "psf"
        assert repo_data.repo == "requests"
        assert repo_data.description == "Python HTTP library"
        assert len(repo_data.directory_tree) > 0
```

**Step 2: Implement `app/services/__init__.py`**

```python
# app/services/__init__.py
```

**Step 3: Implement `app/services/github_client.py`**

```python
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

        tree_lines: list[str] = []
        for path in sorted(paths):
            parts = path.split("/")
            indent = "  " * (len(parts) - 1)
            # Add directory prefixes for intermediate directories
            tree_lines.append(f"{indent}{parts[-1]}")

        # Deduplicate and add directory markers
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

            repo_info = repo_resp.json()
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

            tree_data = tree_resp.json()
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
                except (httpx.TimeoutException, httpx.HTTPError):
                    # Skip files that fail to download
                    continue

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
```

**Step 4: Run tests**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/python -m pytest tests/test_github_client.py -v`
Expected: All tests PASS.

NOTE: You may need to install `pytest-asyncio` first:
Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/pip install pytest-asyncio`

**Step 5: Commit**

```bash
git add app/services/__init__.py app/services/github_client.py tests/test_github_client.py
git commit -m "feat: add GitHub client for fetching repo metadata, tree, and file contents"
```

---

## Phase 4: LLM Summarizer (Exit Criteria: Can generate structured summary from repo data)

### Task 6: Create LLM Summarizer Service

**Files:**
- Create: `app/services/summarizer.py`
- Create: `tests/test_summarizer.py`

**Step 1: Write tests first**

Create `tests/test_summarizer.py`:

```python
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
```

**Step 2: Implement `app/services/summarizer.py`**

```python
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
                f"LLM summarization failed: {e.message}",
                status_code=502,
            )

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
```

**Step 3: Run tests**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/python -m pytest tests/test_summarizer.py -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add app/services/summarizer.py tests/test_summarizer.py
git commit -m "feat: add LLM summarizer service with OpenAI integration"
```

---

## Phase 5: Wire Everything Together (Exit Criteria: Full endpoint works end-to-end)

### Task 7: Connect Router to Services

**Files:**
- Modify: `app/routers/summarize.py` (replace stub with real logic)
- Modify: `app/main.py` (add .env loading)
- Modify: `tests/test_api.py` (add full integration test)

**Step 1: Update `app/main.py` to load .env**

```python
import os
from pathlib import Path
from fastapi import FastAPI
from app.routers import summarize


def _load_dotenv():
    """Load .env file if it exists (lightweight, no extra dependency)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

app = FastAPI(
    title="GitHub Repo Summarizer",
    description="Summarize GitHub repositories using LLM",
    version="0.1.0",
)

app.include_router(summarize.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

**Step 2: Update `app/routers/summarize.py` with real logic**

```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.models import SummarizeRequest, SummarizeResponse, ErrorResponse
from app.services.github_client import GitHubClient, GitHubClientError
from app.services.summarizer import Summarizer, SummarizerError

router = APIRouter()


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def summarize_repo(request: SummarizeRequest):
    github_client = GitHubClient()
    summarizer = Summarizer()

    # 1. Parse URL
    owner, repo = github_client.parse_github_url(request.github_url)

    # 2. Fetch repo data from GitHub
    try:
        repo_data = await github_client.fetch_repo_data(owner, repo)
    except GitHubClientError as e:
        return JSONResponse(
            status_code=e.status_code,
            content=ErrorResponse(message=e.message).model_dump(),
        )

    # 3. Summarize with LLM
    try:
        result = await summarizer.summarize(repo_data)
    except SummarizerError as e:
        return JSONResponse(
            status_code=e.status_code,
            content=ErrorResponse(message=e.message).model_dump(),
        )

    return SummarizeResponse(**result)
```

**Step 3: Update `tests/test_api.py` with full mocked integration test**

Append to `tests/test_api.py`:

```python
import json
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.github_client import RepoData


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
```

**Step 4: Run all tests**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add app/main.py app/routers/summarize.py tests/test_api.py
git commit -m "feat: wire up /summarize endpoint with GitHub client and LLM summarizer"
```

---

## Phase 6: README and Final Polish (Exit Criteria: README written, manual test successful)

### Task 8: Create README

**Files:**
- Create: `README.md`

**Step 1: Write README.md**

```markdown
# GitHub Repo Summarizer API

A FastAPI service that takes a GitHub repository URL and returns an AI-generated
summary including a description, technologies used, and project structure analysis.

## Quick Start

### Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/) package manager
- OpenAI API key

### Setup

1. Clone the repository and install dependencies:

   ```bash
   poetry install
   ```

2. Set your OpenAI API key in `.env`:

   ```
   OPENAI_API_KEY=sk-your-key-here
   ```

3. Run the server:

   ```bash
   poetry run uvicorn app.main:app --reload
   ```

   The server starts at `http://localhost:8000`.

## Usage

### POST /summarize

Summarize a GitHub repository:

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

**Response:**

```json
{
  "summary": "Requests is a popular Python HTTP library designed for human beings...",
  "technologies": ["Python", "urllib3", "chardet", "certifi"],
  "structure": "The project has a clean structure with the main library code in src/requests/..."
}
```

### GET /health

Health check endpoint:

```bash
curl http://localhost:8000/health
```

### Error Responses

All errors return:

```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

| Status | Meaning |
|--------|---------|
| 400 | Invalid GitHub URL format |
| 404 | Repository not found |
| 422 | Repository is empty or has no analyzable files |
| 429 | GitHub API rate limit exceeded |
| 502 | GitHub or OpenAI API error |
| 504 | OpenAI request timeout |

## How It Works

1. **URL Parsing** - Extracts owner/repo from the GitHub URL
2. **Repo Tree Fetch** - Uses GitHub's Git Trees API to get the full file listing in one API call
3. **File Filtering** - Excludes binary files, lock files, vendor directories, and other noise
4. **Priority Ranking** - Ranks files into tiers:
   - Tier 1: README (highest signal)
   - Tier 2: Config files (package.json, Dockerfile, etc.)
   - Tier 3: Source code (entry points first, then by depth/size)
5. **Content Fetching** - Downloads top-priority files via raw.githubusercontent.com (no rate limit)
6. **LLM Analysis** - Sends directory tree + file contents to OpenAI for structured analysis

## Configuration

Environment variables (set in `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| (in config.py) | `gpt-4o-mini` | OpenAI model to use |
| (in config.py) | `100000` | Max characters of repo content to send to LLM |

## Running Tests

```bash
poetry run pytest tests/ -v
```

## Rate Limits

This service uses the GitHub API without authentication (60 requests/hour).
Each summarization uses 2 GitHub API calls (repo metadata + tree).
File content is fetched from raw.githubusercontent.com which has no rate limit.

## API Documentation

Interactive docs available at `http://localhost:8000/docs` (Swagger UI).
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, usage, and architecture docs"
```

### Task 9: Manual End-to-End Test

**Step 1: Start the server**

Run: `cd /Users/eyal.levy/dev/git/elevy30/nebius && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &`

**Step 2: Test health endpoint**

Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

**Step 3: Test /summarize with a small repo**

Run:
```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/keleshev/schema"}' \
  --max-time 60
```
Expected: JSON with summary, technologies, structure fields.

**Step 4: Test error handling - invalid URL**

Run:
```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "not-a-url"}'
```
Expected: 422 validation error.

**Step 5: Test error handling - nonexistent repo**

Run:
```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/nonexistent-user-abc123/nonexistent-repo"}'
```
Expected: 404 with error message.

**Step 6: Stop the server**

Run: `kill %1` (or the PID of the uvicorn process)

**Step 7: Final commit if any adjustments made**

```bash
git add -A
git commit -m "chore: final polish after manual testing"
```

---

## Risks

| Risk | P (1-5) | I (1-5) | Score | Mitigation |
|------|---------|---------|-------|------------|
| GitHub rate limit (60/hr) | 3 | 3 | 9 | Each request uses only 2 API calls; raw content is free |
| OpenAI API timeout on large context | 2 | 3 | 6 | 120s timeout, can reduce content budget |
| LLM returns malformed JSON | 3 | 2 | 6 | Strip markdown fences, validate fields, raise clear error |
| Very large repo tree (>100k files) | 2 | 3 | 6 | Tree API handles truncation; file filter reduces set |
| GitHub API changes | 1 | 4 | 4 | Using stable v3 REST API |
| OpenAI model deprecation | 1 | 3 | 3 | Model configurable via Settings |

---

## Success Criteria

- [ ] `POST /summarize` returns structured JSON for valid repos
- [ ] Invalid URLs return 400/422 errors
- [ ] Nonexistent repos return 404
- [ ] All unit tests pass
- [ ] Server starts and health check works
- [ ] README documents setup and usage
- [ ] Large repos handled gracefully (file filtering + budget)

---

## Checkpoints

- [CHECKPOINT] OpenAI model: using gpt-4o-mini (recommend: cheapest with 128k context, good enough for summarization)
- [CHECKPOINT] Token budget: 100,000 chars (~25k tokens). Conservative but works for all models. Can increase for gpt-4o-mini.
- [CHECKPOINT] No python-dotenv dependency: using a lightweight built-in .env loader to avoid extra dependency. Could use python-dotenv if preferred.
- [CHECKPOINT] No auth for GitHub: using unauthenticated API (60 req/hr). Could add GITHUB_TOKEN env var for higher limits.
- [CHECKPOINT] pytest-asyncio needed: not in pyproject.toml, will need `pip install pytest-asyncio` or add to dev deps.