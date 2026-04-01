import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parents[4] / ".env"
load_dotenv(_env_path)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GENERATOR_MODEL = "gpt-4o-mini"
JUDGE_MODEL = "gpt-4o"
