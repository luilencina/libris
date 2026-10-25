import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", str(BACKEND_DIR / "data"))).resolve()
JOBS_DIR = DATA_DIR / "jobs"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
APP_ENV = os.getenv("APP_ENV", "development").strip().casefold()
APP_SESSION_SECRET = os.getenv("APP_SESSION_SECRET", "").strip()
FRONTEND_URL = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
GITHUB_CALLBACK_URL = os.getenv("GITHUB_CALLBACK_URL", "").strip()
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "").strip()
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
CHUNK_CHAR_LIMIT = max(1500, int(os.getenv("CHUNK_CHAR_LIMIT", "6500")))
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173").split(",")
    if origin.strip()
]

JOBS_DIR.mkdir(parents=True, exist_ok=True)
