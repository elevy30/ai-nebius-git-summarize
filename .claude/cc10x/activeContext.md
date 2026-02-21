# Active Context
<!-- cc10x:session-memory contract — do not remove required headings -->

## Current Focus
- GitHub Repo Summarizer API - BUILD COMPLETE, E2E VERIFIED

## Recent Changes
- [2026-02-21] Built complete GitHub Repo Summarizer API (all 6 phases, 49 tests)
- Created: app/config.py, app/models.py, app/main.py
- Created: app/routers/summarize.py (POST /summarize + error handling)
- Created: app/utils/file_filter.py (exclude + priority ranking)
- Created: app/services/github_client.py (Trees API + raw content fetch)
- Created: app/services/summarizer.py (OpenAI LLM integration)
- Created: tests/test_models.py, test_file_filter.py, test_github_client.py, test_summarizer.py, test_api.py
- Created: README.md with setup/usage docs

## Next Steps
1. E2E test PASSED (keleshev/schema repo summarized successfully)
2. Optional: Add GITHUB_TOKEN support for higher rate limits
3. Optional: Add caching for repeated repo lookups

## Decisions
- GitHub strategy: Git Trees API + raw.githubusercontent.com (2 API calls, unlimited raw fetches)
- File priority: 3-tier system (README > config > source) with token budget allocation
- Token budget: 100,000 chars (~25k tokens), conservative for all models
- LLM model: gpt-4o-mini (128k context, cost-effective)
- No python-dotenv: lightweight built-in .env loader
- Error mapping: specific HTTP status per failure type (404, 429, 502, 504)

## Learnings
- Git Trees API + raw.githubusercontent.com is optimal for unauthenticated GitHub fetching (2 API calls + unlimited raw)
- 3-tier file priority gives LLM best understanding of repos (README > config > source)
- Python 3.14 universal binary (x86_64+arm64) causes arch mismatch with pydantic_core -- use `arch -arm64` for uvicorn
- pytest-asyncio 0.25.3 works with asyncio_mode="auto" in pyproject.toml
- Mock side_effect list must match exact number of API calls (GitHub client makes 2 + N raw content calls)
- jiter package (OpenAI SDK dep) may install for wrong arch -- use `arch -arm64 pip install --force-reinstall jiter`
- Always wrap .json() calls in try/except for HTTP responses (can crash on malformed data)
- Add catch-all Exception handler in routers for unexpected errors

## References
- Plan: `docs/plans/2026-02-21-github-repo-summarizer-plan.md`
- Design: N/A (self-contained in plan)
- Research: N/A

## Blockers
- [None]

## Last Updated
2026-02-21