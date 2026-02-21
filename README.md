# GitHub Repo Summarizer API

A FastAPI service that takes a GitHub repository URL and returns an AI-generated
summary including a description, technologies used, and project structure analysis.

## Setup and Run Instructions

### Prerequisites

- Python 3.10+
- pip

### Step-by-step setup



1. Install dependencies:

   ```bash
    poetry install --no-root
   ```

2. Set your OpenAI API key as an environment variable:

   ```bash
   export OPENAI_API_KEY=sk-your-key-here
   ```

3. Start the server:

   ```bash
   poetry run python main.py
   ```

4. Test it:

   ```bash
   curl -X POST http://localhost:8000/summarize \
     -H "Content-Type: application/json" \
     -d '{"github_url": "https://github.com/psf/requests"}'
   ```

## Model Choice

I chose **gpt-4o-mini** because it offers a 128k token context window (enough for large repos) at a very low cost, while still producing high-quality structured summaries. It strikes the best balance between cost, speed, and output quality for this use case.

## Approach to Handling Repository Contents

### What I include

- **README files** (highest priority) — they contain the most concentrated description of what a project does
- **Config/manifest files** (package.json, pyproject.toml, Dockerfile, Makefile, CI workflows, etc.) — these reveal the tech stack, dependencies, and build process
- **Key source files** — entry points (main.py, index.ts, etc.) and shallow source files, sorted by depth and size so the LLM sees the most important code first
- **Full directory tree** — gives the LLM structural context even for files not included in full

### What I skip

- **Binary files** (images, fonts, compiled files, archives)
- **Lock files** (package-lock.json, poetry.lock, yarn.lock, etc.) — large, no signal
- **Vendor/dependency directories** (node_modules/, .venv/, vendor/, dist/, build/)
- **Generated/minified files** (.min.js, .min.css, source maps, chunks)
- **Files over 100KB** — likely generated or data files

### Why this approach

Repositories can have thousands of files, but most understanding comes from a small subset. I use a **3-tier priority system** that allocates a 100,000-character budget (~25k tokens):

1. **Tier 1 (30% budget):** README — highest signal-to-noise ratio
2. **Tier 2 (20% budget):** Config files — reveal tech stack without reading code
3. **Tier 3 (50% budget):** Source code — entry points and shallow files first

The GitHub Git Trees API fetches the entire file listing in a single API call, then file contents are downloaded via `raw.githubusercontent.com` which has no rate limit. This means each request uses only **2 GitHub API calls** regardless of repo size.

## API Endpoints

### POST /summarize

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

### Error Responses

```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

| Status | Meaning |
|--------|---------|
| 404    | Repository not found |
| 422    | Invalid URL or empty repository |
| 429    | GitHub API rate limit exceeded |
| 502    | GitHub or OpenAI API error |
| 504    | OpenAI request timeout |

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Configuration

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `OPENAI_API_KEY`    | Yes      | OpenAI API key |

Additional settings can be adjusted in `app/config.py`:
- `openai_model`: defaults to `gpt-4o-mini`
- `max_content_chars`: defaults to `100000` (~25k tokens)
