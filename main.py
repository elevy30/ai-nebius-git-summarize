import os
from pathlib import Path
from fastapi import FastAPI
from app.routers import health, summarize


def _load_dotenv():
    """Load .env file if it exists (lightweight, no extra dependency)."""
    env_path = Path(__file__).resolve().parent / ".env"
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

app.include_router(health.router)
app.include_router(summarize.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)