"""Parse SSA's Compassionate Allowances (CAL) condition list from the saved ssa.gov page."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from app import config

SOURCE_URL = "https://www.ssa.gov/compassionateallowances/conditions.htm"
HTML_PATH = config.DATA_DIR / "cal" / "conditions.html"


def parse_cal(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    links = [a for a in soup.find_all("a") if "poms.nsf" in (a.get("href") or "")]
    out, seen = [], set()
    for a in links:
        name = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        name = re.sub(r"\s*\(New\)$", "", name)
        if name and name not in seen:
            seen.add(name)
            out.append({"name": name, "poms_url": a.get("href")})
    if len(out) < 100:
        raise ValueError(f"Only {len(out)} CAL conditions parsed - is this the CAL conditions page?")
    return out


def source_meta(html_path: Path = HTML_PATH) -> dict:
    raw = html_path.read_bytes()
    meta = {
        "source_url": SOURCE_URL,
        "retrieved_at": datetime.fromtimestamp(html_path.stat().st_mtime, timezone.utc).isoformat(),
        "retrieval_method": "Saved from ssa.gov in a browser by the project owner (automated fetch returned HTTP 403).",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "file": html_path.name,
    }
    (html_path.parent / "source.json").write_text(json.dumps(meta, indent=2))
    return meta
