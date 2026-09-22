import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = BASE_DIR / "jobs.db"

RSS_USER_AGENT = os.getenv("RSS_USER_AGENT", "job-tracker/1.0 (r/forhire takip scripti)")
RSS_LIMIT_MAX = 100

DEFAULT_SUBREDDITS = ["forhire", "slavelabour", "jobbit"]
DEFAULT_MAX_AGE_DAYS = 5
DEFAULT_INTERVAL_SEC = 0  # 0 = scheduler kapalı
DEFAULT_FETCH_LIMIT = 100
DEFAULT_KEYWORDS = ""

HIRED_FLAIRS = {"hired", "completed", "closed", "filled"}
HIRING_FLAIRS = {"hiring", "job posting", "looking to hire", "request"}
FOR_HIRE_FLAIRS = {"for hire", "offering", "portfolio"}

TITLE_HIRING_MARKERS = (
    "hiring", "looking for", "looking to hire", "need a", "need an", "need someone",
    "[request]", "request:", "freelance job", "project for",
)
TITLE_FOR_HIRE_MARKERS = (
    "[for hire]", "[offer]", "for hire", "offering", "portfolio", "available for",
    "open for work", "offer:",
)

# --- AI filtre ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # ollama | gemini
LLM_MODEL = os.getenv("LLM_MODEL", "llama3")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
AI_THRESHOLD = int(os.getenv("AI_THRESHOLD", "50"))  # 0-100; alti elenir

FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
