# Patterns
<!-- cc10x:session-memory contract — do not remove required headings -->

## Architecture Patterns
- 3-layer FastAPI: routers -> services -> utils
- Pydantic models in app/models.py for request/response validation
- Settings via dataclass in app/config.py (no pydantic-settings dependency)
- Lightweight .env loader in app/main.py (no python-dotenv dependency)

## File Structure
- `app/` - Application package (main.py, config.py, models.py)
- `app/routers/` - FastAPI route handlers
- `app/services/` - Business logic (github_client.py, summarizer.py)
- `app/utils/` - Pure utility functions (file_filter.py)
- `tests/` - pytest test files

## Dependencies
- fastapi: Web framework
- uvicorn: ASGI server
- httpx: Async HTTP client (GitHub API + raw content)
- openai: OpenAI Python SDK (async)
- pytest + pytest-asyncio: Testing (pytest-asyncio needed for async tests)

## Testing Patterns
- asyncio_mode = "auto" in pyproject.toml -- no need for @pytest.mark.asyncio decorators
- Mock side_effect list must have exactly as many items as API calls made
- Use `patch("app.routers.summarize.GitHubClient")` to mock at the import site, not the definition site
- FastAPI TestClient is synchronous, async endpoints are handled automatically

## Common Gotchas
- raw.githubusercontent.com does NOT count against GitHub API rate limit (use it for file content)
- GitHub API returns 403 (not 429) when rate limited for unauthenticated requests
- OpenAI may wrap JSON response in markdown fences even when told not to -- strip them
- pytest-asyncio not in pyproject.toml -- must install separately or add to dev deps
- Python 3.14 universal binary: pydantic_core .so may be arm64-only; use `arch -arm64` to run uvicorn
- GitHubClient.fetch_repo_data makes 2 + N API calls (repo + tree + N raw content fetches)
- jiter (OpenAI dep) may install for wrong arch -- `arch -arm64 pip install --force-reinstall jiter`
- Always wrap .json() on HTTP responses in try/except (malformed responses crash endpoint)
- Add catch-all `except Exception` in router for unhandled errors (returns 500 with message)