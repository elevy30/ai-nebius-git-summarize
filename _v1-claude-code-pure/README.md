# GitHub Repository Summarizer

A FastAPI service that takes a GitHub repository URL and returns a human-readable summary of the project using OpenAI (GPT-4o-mini).

## Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/docs/#installation) package manager
- An OpenAI API key

## Setup

1. **Install dependencies:**

```bash
cd nebius
poetry install --no-root
```

2. **Set your OpenAI API key:**

```bash
export OPENAI_API_KEY="your-openai-api-key-here"
```

Optionally, set a GitHub token to avoid rate limits on large repositories:

```bash
export GITHUB_TOKEN="your-github-token-here"
```

3. **Start the server:**

```bash
poetry run python main.py
```

The server will start on `http://localhost:8000`.

## Usage

Send a POST request to the `/summarize` endpoint:

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

### Response

```json
{
  "summary": "Requests is a popular Python library for making HTTP requests...",
  "technologies": ["Python", "urllib3", "certifi"],
  "structure": "The project follows a standard Python package layout..."
}
```

### Error Response

```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

## How It Works

1. **URL Parsing** — Extracts the owner and repository name from the GitHub URL.
2. **Repository Fetching** — Uses the GitHub API to fetch the full file tree, then selectively downloads the most informative files (README, config files, key source files) while skipping binaries, lock files, and build artifacts.
3. **Context Assembly** — Builds a directory tree and concatenates file contents, staying within LLM context limits (~120K characters).
4. **LLM Analysis** — Sends the assembled context to OpenAI (gpt-4o-mini) which returns a structured JSON analysis of the project.

### Content Selection Strategy

Not all files in a repository are equally informative. The service uses a priority-based approach:

- **Highest priority:** README files, package manifests (package.json, pyproject.toml, Cargo.toml, etc.), Dockerfiles
- **High priority:** Source code files at shallow directory depths
- **Skipped entirely:** Binary files, lock files, node_modules, build outputs, caches, IDE configs

Files are sorted by priority score and fetched until the content budget (120K chars) is reached, ensuring the LLM gets the most relevant information possible.