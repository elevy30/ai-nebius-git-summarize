import json
import os
import re
from typing import Any

import httpx
from openai import AsyncOpenAI
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="GitHub Repository Summarizer")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional, raises rate limits

# Maximum total characters of file content we send to the LLM.
MAX_CONTENT_CHARS = 120_000
# Maximum characters per individual file.
MAX_FILE_CHARS = 8_000
# Maximum number of files whose content we fetch.
MAX_FILES_TO_FETCH = 60

# Directories / path segments to always skip.
SKIP_DIRS = {
    "node_modules", ".git", "vendor", "dist", "build", "__pycache__",
    ".next", ".nuxt", ".output", ".cache", ".tox", ".mypy_cache",
    ".pytest_cache", "venv", ".venv", "env", ".env", "eggs",
    ".eggs", "bower_components", "jspm_packages", ".gradle",
    "target", "out", "bin", "obj", ".idea", ".vscode",
    "coverage", ".nyc_output", "htmlcov",
}

# File extensions to always skip (binary / non-informative).
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".o", ".a",
    ".class", ".jar", ".war", ".ear",
    ".exe", ".bin", ".dat", ".db", ".sqlite", ".sqlite3",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".min.js", ".min.css", ".map",
}

# Filenames to always skip.
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "composer.lock", "Gemfile.lock", "Cargo.lock",
    "go.sum", ".DS_Store", "Thumbs.db",
}

# Files that are high-priority for understanding a project (fetched first).
PRIORITY_FILES = {
    "README.md", "README.rst", "README.txt", "README",
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "go.mod", "build.gradle", "pom.xml",
    "Gemfile", "composer.json", "Makefile", "CMakeLists.txt",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".github/workflows", "requirements.txt",
    "tsconfig.json", "webpack.config.js", "vite.config.ts", "vite.config.js",
}

# Extensions that are likely informative source code.
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".kt", ".scala", ".ex", ".exs", ".erl", ".hs", ".clj",
    ".lua", ".r", ".jl", ".sh", ".bash", ".zsh", ".fish",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".html", ".css",
    ".scss", ".sass", ".less", ".md", ".rst", ".txt",
    ".sql", ".graphql", ".proto", ".tf", ".hcl",
}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SummarizeRequest(BaseModel):
    github_url: str


class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner and repo name from a GitHub URL."""
    pattern = r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$"
    match = re.search(pattern, url.strip().rstrip("/"))
    if not match:
        raise ValueError(f"Invalid GitHub repository URL: {url}")
    return match.group(1), match.group(2)


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _should_skip(path: str) -> bool:
    """Return True if a file path should be excluded from analysis."""
    parts = path.split("/")

    # Skip if any directory segment is in the skip list.
    for part in parts[:-1]:
        if part in SKIP_DIRS:
            return True

    filename = parts[-1]
    if filename in SKIP_FILES:
        return True

    # Check extensions (handle compound like .min.js).
    lower = filename.lower()
    for ext in SKIP_EXTENSIONS:
        if lower.endswith(ext):
            return True

    return False


def _priority_score(path: str) -> int:
    """Lower score = higher priority. Used to sort files for fetching."""
    filename = path.split("/")[-1]
    depth = path.count("/")

    # Exact priority file matches.
    if filename in PRIORITY_FILES:
        return -1000 + depth

    # Config / manifest files at shallow depth.
    lower = filename.lower()
    if lower in {"readme.md", "readme.rst", "readme.txt", "readme"}:
        return -900

    config_names = {
        "package.json", "pyproject.toml", "setup.py", "cargo.toml",
        "go.mod", "gemfile", "composer.json", "pom.xml", "build.gradle",
        "makefile", "cmakelists.txt", "dockerfile",
    }
    if lower in config_names:
        return -800 + depth

    # Source files — prefer shallower files.
    _, ext = os.path.splitext(lower)
    if ext in SOURCE_EXTENSIONS:
        return depth * 10

    return 500 + depth


async def fetch_repo_tree(client: httpx.AsyncClient, owner: str, repo: str) -> list[dict[str, Any]]:
    """Fetch the full file tree of a repo using the Git Trees API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    resp = await client.get(url, headers=_github_headers(), timeout=30)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Repository {owner}/{repo} not found")
    if resp.status_code == 403:
        raise HTTPException(status_code=429, detail="GitHub API rate limit exceeded. Set GITHUB_TOKEN to increase limits.")
    resp.raise_for_status()
    data = resp.json()
    return [item for item in data.get("tree", []) if item.get("type") == "blob"]


async def fetch_file_content(client: httpx.AsyncClient, owner: str, repo: str, path: str) -> str | None:
    """Fetch raw file content from GitHub."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
    try:
        resp = await client.get(url, headers=_github_headers(), timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return None
        # Skip binary content.
        content_type = resp.headers.get("content-type", "")
        if "application/octet-stream" in content_type and not path.endswith((".md", ".txt", ".rst")):
            return None
        text = resp.text
        if "\x00" in text[:1000]:  # binary heuristic
            return None
        return text[:MAX_FILE_CHARS]
    except Exception:
        return None


def build_tree_string(file_paths: list[str]) -> str:
    """Build a directory-tree representation from a list of file paths."""
    tree: dict = {}
    for path in sorted(file_paths):
        parts = path.split("/")
        node = tree
        for part in parts:
            node = node.setdefault(part, {})

    lines: list[str] = []

    def _render(node: dict, prefix: str = ""):
        entries = sorted(node.keys())
        for i, name in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "`-- " if is_last else "|-- "
            lines.append(f"{prefix}{connector}{name}")
            if node[name]:  # has children (directory)
                extension = "    " if is_last else "|   "
                _render(node[name], prefix + extension)

    _render(tree)
    # Cap tree length.
    if len(lines) > 200:
        lines = lines[:200] + [f"... and {len(lines) - 200} more entries"]
    return "\n".join(lines)


async def gather_repo_context(owner: str, repo: str) -> str:
    """
    Fetch repository metadata, directory tree, and key file contents.
    Returns a single string ready to be sent to the LLM.
    """
    async with httpx.AsyncClient() as client:
        # 1. Get file tree.
        tree_items = await fetch_repo_tree(client, owner, repo)
        all_paths = [item["path"] for item in tree_items]

        # 2. Filter and sort files.
        candidate_paths = [p for p in all_paths if not _should_skip(p)]
        candidate_paths.sort(key=_priority_score)

        # 3. Build directory tree string (from ALL non-skipped paths).
        tree_str = build_tree_string(candidate_paths)

        # 4. Fetch content of the most important files.
        files_to_fetch = candidate_paths[:MAX_FILES_TO_FETCH]
        file_contents: dict[str, str] = {}
        total_chars = 0

        for path in files_to_fetch:
            if total_chars >= MAX_CONTENT_CHARS:
                break
            content = await fetch_file_content(client, owner, repo, path)
            if content:
                file_contents[path] = content
                total_chars += len(content)

    # 5. Assemble context document.
    sections = [
        f"# Repository: {owner}/{repo}\n",
        "## Directory Structure\n```",
        tree_str,
        "```\n",
    ]

    if file_contents:
        sections.append("## File Contents\n")
        for path, content in file_contents.items():
            sections.append(f"### {path}\n```")
            sections.append(content)
            sections.append("```\n")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

LLM_SYSTEM_PROMPT = """You are a software project analyst. Given information about a GitHub repository
(directory structure and file contents), produce a structured analysis.

You MUST respond with valid JSON matching this exact schema:
{
  "summary": "A clear, human-readable description of what the project does, its purpose, and key features. 2-4 sentences.",
  "technologies": ["List", "of", "main", "technologies", "languages", "frameworks", "and", "libraries"],
  "structure": "Brief description of how the project is organized — main directories and their purposes. 1-3 sentences."
}

Guidelines:
- For "summary": Focus on WHAT the project does and WHY someone would use it. Be specific, not generic.
- For "technologies": Include the primary programming language(s), frameworks, key libraries, build tools, and infrastructure tools. Be specific (e.g. "FastAPI" not just "Python web framework").
- For "structure": Describe the high-level layout. Mention important directories and what they contain.
- Return ONLY the JSON object, no markdown code fences, no extra text."""


async def call_llm(context: str) -> dict[str, Any]:
    """Send the repository context to OpenAI and parse the structured response."""
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY environment variable is not set",
        )

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    user_prompt = f"""Analyze the following GitHub repository and provide a structured summary.

{context}

Remember: respond with ONLY a valid JSON object with keys "summary", "technologies", and "structure"."""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    raw_text = response.choices[0].message.content.strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail=f"LLM returned invalid JSON: {raw_text[:500]}",
        )

    # Validate expected keys.
    for key in ("summary", "technologies", "structure"):
        if key not in result:
            raise HTTPException(
                status_code=502,
                detail=f"LLM response missing required key: {key}",
            )

    return result


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(request: SummarizeRequest):
    # 1. Parse and validate the GitHub URL.
    try:
        owner, repo = parse_github_url(request.github_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 2. Gather repository context.
    try:
        context = await gather_repo_context(owner, repo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch repository data: {e}")

    # 3. Call LLM for analysis.
    try:
        result = await call_llm(context)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}")

    return SummarizeResponse(
        summary=result["summary"],
        technologies=result["technologies"],
        structure=result["structure"],
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)