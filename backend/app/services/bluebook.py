"""Parse SSA Blue Book 1.00 (Musculoskeletal Disorders - Adult) HTML into verbatim chunks.

The listing text is NEVER written by hand or by a model: every chunk is the text of an element
on SSA's page, keyed by SSA's own anchor ids (e.g. id="1_15B3a" -> criterion "1.15B3a").
Only whitespace is normalized.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from app import config

SOURCE_URL = "https://www.ssa.gov/disability/professionals/bluebook/1.00-Musculoskeletal-Adult.htm"
BLUEBOOK_DIR = config.DATA_DIR / "bluebook"
HTML_PATH = BLUEBOOK_DIR / "1.00-Musculoskeletal-Adult.html"
PILOT_LISTINGS = [f"1.{n}" for n in range(15, 24)]  # 1.15 - 1.23
_ID_RE = re.compile(r"^1_(00|1[5-9]|2[0-3])[A-Za-z0-9]*$")
_REF_RE = re.compile(r"1\.00([A-Z](?:\d+)?(?:[a-z])?(?:\((?:i|ii|iii|iv)\))?)")


@dataclass
class Chunk:
    criterion_id: str
    listing_code: str
    level: str
    parent_id: str | None
    heading: str  # this element's own text
    text: str  # own text + all descendant criteria (and AND/OR connectors for listings), verbatim
    seq: int
    children: list[str] = field(default_factory=list)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _level(cid: str) -> str:
    if cid.startswith("1.00"):
        return "intro"
    rest = cid[4:]
    if rest == "":
        return "listing"
    return "criterion" if len(rest) == 1 else "subcriterion"


def parse_bluebook(html: str) -> list[Chunk]:
    soup = BeautifulSoup(html, "html.parser")
    first = soup.find(id="1_00")
    if first is None:
        raise ValueError("Blue Book HTML missing expected anchor id='1_00' - is this the 1.00 Musculoskeletal page?")
    # Walk all <p> elements in document order inside the section.
    paras = first.find_all_next("p")
    rows: list[tuple[str | None, str]] = []  # (criterion_id or None for connectors, own text)
    seen: dict[str, int] = {}
    started = False
    for p in [first] + paras:
        pid = p.get("id")
        text = clean(p.get_text(""))
        if pid and _ID_RE.match(pid):
            started = True
            cid = pid.replace("_", ".", 1)
            if cid in seen:  # SSA page has a duplicated anchor (1_00A3); keep both, disambiguate
                seen[cid] += 1
                cid = f"{cid}#{seen[cid]}"
            else:
                seen[cid] = 1
            rows.append((cid, text))
        elif started and text in ("AND", "OR"):
            rows.append((None, text))
    ids = [r[0] for r in rows if r[0]]

    def parent_of(cid: str) -> str | None:
        base = cid.split("#")[0]
        cands = [i for i in ids if i != cid and "#" not in i and base.startswith(i) and len(i) < len(base)]
        cands = [c for c in cands if c not in ("1.00",) or base.startswith("1.00")]
        return max(cands, key=len) if cands else None

    chunks: dict[str, Chunk] = {}
    for seq, (cid, text) in enumerate(rows):
        if cid is None:
            continue
        code = cid[:4]
        chunks[cid] = Chunk(cid, code, _level(cid.split("#")[0]), parent_of(cid), text, text, seq)
    for c in chunks.values():
        if c.parent_id and c.parent_id in chunks:
            chunks[c.parent_id].children.append(c.criterion_id)
    # Composite text: own text + all descendants in page order. For a listing, the AND/OR
    # connectors between its criteria are kept so the logical structure stays verbatim.
    for c in chunks.values():
        idx = [i for i, (cid, _) in enumerate(rows)
               if cid is not None and (cid == c.criterion_id or _is_descendant(cid, c.criterion_id, chunks))]
        keep = set(idx)
        if c.level == "listing" and idx:
            keep |= {i for i in range(idx[0], idx[-1] + 1) if rows[i][0] is None}
        c.text = "\n".join(rows[i][1] for i in sorted(keep))
    return sorted(chunks.values(), key=lambda c: c.seq)


def _is_descendant(cid: str, anc: str, chunks: dict[str, Chunk]) -> bool:
    cur = chunks.get(cid)
    while cur and cur.parent_id:
        if cur.parent_id == anc:
            return True
        cur = chunks.get(cur.parent_id)
    return False


def referenced_sections(text: str) -> list[str]:
    """'(see 1.00C6e(i))' -> ['1.00C6ei'] etc. Returns unique ids in order of appearance."""
    out = []
    for m in _REF_RE.finditer(text):
        cid = "1.00" + m.group(1).replace("(", "").replace(")", "")
        if cid not in out:
            out.append(cid)
    return out


def source_meta(html_path: Path = HTML_PATH) -> dict:
    meta_path = html_path.parent / "source.json"
    raw = html_path.read_bytes()
    meta = {
        "source_url": SOURCE_URL,
        "retrieved_at": datetime.fromtimestamp(html_path.stat().st_mtime, timezone.utc).isoformat(),
        "retrieval_method": "Saved from ssa.gov in a browser by the project owner (automated fetch returned HTTP 403).",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "file": html_path.name,
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta


_MARKER_RE = re.compile(r"^(?:(?:[A-Z]|\d{1,2}|[a-z]|i|ii|iii|iv)\.|\((?:i|ii|iii|iv)\))\s+")


def criterion_body(heading: str) -> str:
    """Strip the leading enumerator SSA prints ("A. ", "1. ", "a. ") so the UI can show
    "1.15A Neuro-anatomic..." instead of "1.15A A. Neuro-anatomic..." (rendered as "1.15AA")."""
    return _MARKER_RE.sub("", heading, count=1).strip()


def display_label(criterion_id: str, heading: str) -> str:
    return f"{criterion_id} {criterion_body(heading)}"


def listing_name(heading: str) -> str:
    """'1.15 Disorders of ... nerve root(s) (see 1.00F), documented by A, B, C, and D:' -> 'Disorders of ... nerve root(s)'."""
    name = re.sub(r"^1\.\d{2}\s+", "", heading)
    name = re.split(r",\s*documented by|\s*\(see 1\.00", name)[0]
    return name.strip(" :,")


def listing_logic(heading: str) -> tuple[str, list[str]]:
    """Parse 'documented by A, B, C, and D' -> ('all', [A,B,C,D]); 'A, B, C, or D' -> ('any', [...])."""
    m = re.search(r"documented by ([A-Z](?:[ ,]+(?:and|or)?\s*[A-Z])*)", heading)
    if not m:
        return "all", []
    clause = m.group(1)
    letters = re.findall(r"\b([A-Z])\b", clause)
    return ("any" if re.search(r"\bor\b", clause) else "all"), letters
