"""Environment-driven configuration. All secrets come from the repo-root .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

PROMPTS_DIR = REPO_ROOT / "prompts"
DATA_DIR = REPO_ROOT / "data"
UPLOAD_DIR = REPO_ROOT / "backend" / "storage" / "uploads"
DB_PATH = Path(os.getenv("DB_PATH", REPO_ROOT / "backend" / "storage" / "copilot.db"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
# Cheaper model for bulk work: page tagging, map summaries, synthetic note generation.
OPENAI_FAST_MODEL = os.getenv("OPENAI_FAST_MODEL", "gpt-4.1-mini")

# Approximate USD per 1M tokens for cost reporting. VERIFY against OpenAI's current pricing page.
# Format: "model=input/output,model=input/output"
_DEFAULT_PRICES = "gpt-4.1=2.00/8.00,gpt-4.1-mini=0.40/1.60,text-embedding-3-small=0.02/0"
PRICES: dict[str, tuple[float, float]] = {}
for _item in os.getenv("MODEL_PRICES_PER_1M", _DEFAULT_PRICES).split(","):
    if "=" in _item:
        _m, _p = _item.split("=", 1)
        _i, _o = (_p.split("/") + ["0"])[:2]
        PRICES[_m.strip()] = (float(_i), float(_o))


def price_for(model: str) -> tuple[float, float]:
    """Match dated snapshots (gpt-4.1-2025-04-14) to their base model price."""
    best = max((m for m in PRICES if model.startswith(m)), key=len, default=None)
    return PRICES.get(best, (0.0, 0.0)) if best else (0.0, 0.0)

# Scale pipeline knobs
OCR_MIN_CHARS = int(os.getenv("OCR_MIN_CHARS", "40"))  # pages with less extractable text get OCR
NEAR_DUP_JACCARD = float(os.getenv("NEAR_DUP_JACCARD", "0.9"))
MAP_BATCH_PAGES = int(os.getenv("MAP_BATCH_PAGES", "20"))
MAP_BATCH_CHARS = int(os.getenv("MAP_BATCH_CHARS", "45000"))
LLM_WORKERS = int(os.getenv("LLM_WORKERS", "8"))
LISTING_PAGES_PER_CRITERION = int(os.getenv("LISTING_PAGES_PER_CRITERION", "6"))
LISTING_MAX_PAGES = int(os.getenv("LISTING_MAX_PAGES", "40"))

# Missing-evidence thresholds
IMAGING_RECENCY_MONTHS = int(os.getenv("IMAGING_RECENCY_MONTHS", "12"))
STALE_RECORD_MONTHS = int(os.getenv("STALE_RECORD_MONTHS", "12"))

# Citation verification threshold (0..1) for fuzzy matching
VERIFY_THRESHOLD = float(os.getenv("VERIFY_THRESHOLD", "0.85"))

DEMO_EXAMINER = {"id": 1, "name": "Demo Examiner (J. Rivera)", "role": "Disability Examiner"}
