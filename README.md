# DDS Examiner Copilot (MVP prototype)

> **Prototype. Synthetic data only. AI output is advisory; examiners make all determinations.**

A working MVP of the copilot described in the SSA proposal. It helps state Disability Determination
Services (DDS) examiners review adult musculoskeletal claims (Blue Book 1.00, listings 1.15 to 1.23)
faster. The core rule is that **the AI assists and never decides**:

- Every AI statement cites a source document, a page, and a verbatim quote.
- A citation verifier checks each quote against the stored page text. Anything that fails is shown
  as **Unverified** and is never presented as fact.
- Only a human can record a determination. They must first confirm they reviewed the cited evidence.
- Every AI output and every human action is logged per claim and can be exported as JSON.

The proposal targets Accenture Federal's FedGenius. This MVP puts every LLM call behind an
`LLMProvider` interface (`backend/app/llm/base.py`). OpenAI is the default adapter. Adding FedGenius
means writing `fedgenius_provider.py` and registering it in `backend/app/llm/registry.py`.

---

## Setup

Requirements: Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 20+, and an OpenAI API key.

```bash
make setup          # installs backend + frontend deps, generates synthetic PDFs, creates .env
# edit .env  ->  OPENAI_API_KEY=...   (OPENAI_MODEL / OPENAI_EMBEDDING_MODEL optional)
make ingest         # loads Blue Book 1.00 + CAL list into the vector store (embeddings)
make seed           # optional: seeded demo history for the metrics dashboard
make dev            # backend http://127.0.0.1:8000/docs  +  frontend http://localhost:5173
```

Other commands: `make test` (pytest), `make eval` (scores the full pipeline on all synthetic cases),
`make synth` (regenerates the small PDFs), `make synth-large` (regenerates the ~150 / ~500 / ~1,500-page
cases from cached notes), `make compare-map` (one-time mini vs gpt-4.1 map comparison), and `make reset`
(deletes the local DB and uploads).

OCR needs the Tesseract engine (`brew install tesseract` on macOS); `pytesseract` calls it.

### SSA reference text (Blue Book and CAL list)
The listing criteria and Compassionate Allowances (CAL) list are **never written from memory**. They
are parsed from SSA's own pages, saved in `data/`:

| File | Source |
|---|---|
| `data/bluebook/1.00-Musculoskeletal-Adult.html` | https://www.ssa.gov/disability/professionals/bluebook/1.00-Musculoskeletal-Adult.htm |
| `data/cal/conditions.html` | https://www.ssa.gov/compassionateallowances/conditions.htm |

ssa.gov returns HTTP 403 to scripted downloads, so these were saved from a browser. Each file has a
`source.json` alongside it recording the URL, retrieval time, method, and SHA-256. To refresh them,
save the pages again and run `make ingest`. The chunker keys every chunk to SSA's own anchor ids
(`id="1_15B3a"` becomes criterion `1.15B3a`) and keeps the text verbatim, changing only whitespace.

---

## Architecture

```
frontend/ (React + Vite + TS + Tailwind)      backend/ (FastAPI + SQLite/SQLAlchemy)
  Case list / intake                            routers/      claims, documents, analysis, audit, metrics, listings
  Case view: AI panels | source viewer   --->   services/     extraction, verifier, summary, listing_match,
  Pilot metrics                                               missing_evidence, triage, audit, bluebook, cal
  Listings & CAL reference                      llm/          LLMProvider, OpenAIProvider, FakeProvider (tests)
prompts/<name>/vN.md  (versioned prompts; latest version used; name/version/SHA-256 logged per run)
data/synthetic/       (generator + 6 cases + expected.json)
```

| Feature | How it works |
|---|---|
| 1. Intake | Upload PDFs or load a synthetic case. pdfplumber extracts text **page by page** (the rotated watermark is stripped). The `page` table is the only source of truth. |
| 2. Evidence summary | Six sections, and every bullet has doc + page + quote. The **verifier** normalizes text, then tries an exact match, then a fuzzy word-window match (difflib, threshold 0.85). Each "..."-separated fragment must match on its own. Clicking a citation highlights the matched span in the source viewer. |
| 3. Listing match | RAG: the verified summary is embedded, the top 3 listings are retrieved from the chunk store, and each is assessed **criterion by criterion** (Met / Not met / Insufficient evidence) against verbatim listing text plus referenced 1.00 sections. A Met or Not-met call with no verified citation is shown as insufficient evidence, and the listing's overall call is downgraded to match. |
| 4. Missing evidence | The LLM extracts dated evidence items with citations. **Deterministic rules** over verified items only flag: no imaging within 12 months of filing, no treating source opinion, and no exam within 12 months. The LLM adds clinical gaps. Undocumented listing criteria are flagged too. The LLM then drafts a records request letter the examiner can edit. |
| 5. Triage | The LLM supplies cited **signals** only: a CAL match from a shortlist built from SSA's list, and conflicting opinions. **Rules** map signals to a queue (Fast track / Standard / Senior examiner) with reasons. The examiner accepts or overrides, and an override requires a reason. |
| 6. Decision | Human-only form, never prefilled. Submit is disabled until the evidence-review box is ticked, and the backend enforces the same rule. |
| 7. Audit | `audit_event` and `ai_run` record provider, model, prompt version and SHA, input hash, output, citations, verification results, and every human action. The trail is viewable per claim, with a JSON export. |
| 8. Metrics | Cases processed, intake-to-decision time, triage overrides, unverified-citation rate, and AI listing call vs examiner decision. `make seed` adds clearly flagged demo history. |

---

## Scale pipeline (hundreds to thousands of pages)

| Stage | What happens |
|---|---|
| Ingestion (background job, live progress) | Text per page → OCR (Tesseract) for pages with no text layer, with a confidence score → duplicate detection (exact hash of normalized text; near-duplicates via MinHash with 90% or higher word-overlap similarity and matching clinical dates; fax banners and headers ignored) → tags per page (document type, provider, date of service; rules first, fast model for the rest) → administrative pages (fax covers, bills, reminders, pharmacy fills) are set aside for AI analysis but stay searchable → page chunks embedded (a chunk never spans pages). |
| Summary (map-reduce) | **Map:** the fast model summarizes each document batch (up to 20 pages) into cited bullets, dated events and status statements, and every quote is verified right away. **Reduce:** the main model merges only the *verified* map items per section, referencing them by ID, so final citations are copies of verified page citations. |
| Timeline | Verified events sorted by date, with duplicates merged and routine therapy sessions collapsed into courses. Each entry links to its source page. |
| Conflicts | The main model compares verified status statements (improved vs. worsened, device needed vs. not). Each conflict must cite both sides, which are shown side by side. The AI never picks one. |
| Listing match, relevance, missing evidence, triage | **Search the raw page chunks, never the map summaries.** Each listing criterion retrieves its own top pages (up to 40 per listing); the missing-evidence inventory uses tagged imaging, opinion and exam pages plus raw searches and the most recent exams; the CAL check uses pages found for each CAL candidate. |

Listing *selection* combines the verified summary (top 3) with a raw-records score (its top listing is
added if missing). In testing, raw-only ranking was unreliable because SSA's legal criteria language is
far from clinical wording in embedding space.

## Synthetic cases

All data is fictional. Every PDF page carries a "SYNTHETIC TEST DATA" watermark and footer.

| Case | Scenario | Expected |
|---|---|---|
| `case01_lumbar_radiculopathy` | L4-L5 extrusion, L5 radiculopathy, documented walker need > 12 months | 1.15 criteria appear met → **Fast track** |
| `case02_lumbar_strain` | Mild strain, normal neuro exam, improving | Criteria not met → Standard |
| `case03_knee_conflicting` | Bilateral knee OA; treating source says bilateral canes, CE says no device needed | Insufficient evidence → **Senior examiner** |
| `case04_missing_evidence` | Cervical radiculopathy symptoms; MRI from 2024, no treating opinion, no recent exam | Gaps flagged + letter → Standard |
| `case05_cal_osteosarcoma` | Osteosarcoma of the femur with lung metastases (on SSA's CAL list) | CAL match → **Fast track** |
| `case06_tibial_fracture_healing` | Tibial plateau ORIF, healing on schedule, recovery expected in under 12 months | Duration not met → Standard |

Large cases (`make synth-large`), each multi-provider over 3-4 years, mostly routine/administrative
pages, about 4% scanned image-only pages, fax re-sent duplicates, and hand-written key and conflict pages:

| Case | Pages | Scenario | Key evidence |
|---|---|---|---|
| `case07_medium_lumbar` | 149 | Lumbar L5 radiculopathy; PT "improved" vs ortho "worse" | MRI p.78, walker p.92, source statement p.98 |
| `case08_large_knee_conflict` | 500 | Bilateral knee OA; PT improved → ortho worse → CE says no device | X-ray p.252, canes p.419, CE p.498 |
| `case09_xl_lumbar_ocr` | 1,500 | Lumbar S1 radiculopathy; the key MRI exists only on a **scanned** page | MRI p.752 (OCR), walker p.992, source statement p.1021 |

Expected outcomes are in each case's `expected.json`. They were checked against the verbatim
listing text. Borderline cases accept more than one listing call.

---

## 3-minute demo script

**Setup (before the demo):** run `make reset && make ingest && make seed && make dev` and open
http://localhost:5173.

**0:00. Framing (15 s).** Point to the yellow banner: synthetic data only, and the AI is advisory.
"Every AI sentence has to prove itself against the record."

**0:15. Clear-cut case (75 s).**
1. On **Cases**, load *Marcus T. Hollowell, clear-cut lumbar nerve root compromise*. Note the
   5 documents and 12 pages, extracted page by page.
2. **Evidence summary → Generate.** Point out the citation check line ("N of N quotes found on the
   cited page"). Click the citation on the walker prescription: the source pane jumps to Progress
   Notes p. 2 and highlights the exact sentence.
3. **Listing match → Compare to listings.** Open the 1.15 table. Each criterion (A, B1, B2, B3, C,
   D1) is quoted verbatim from SSA's Blue Book, with Met / Not met / Insufficient evidence and the
   supporting record quotes. Click "Show verbatim listing text" and the source link.
4. **Triage → Suggest.** It suggests *Fast track*, with the rule-based reason "All criteria of
   listing 1.15 appear met with verified citations". Click **Accept suggestion**.
5. **Examiner decision.** The form is empty and the submit button is disabled. Tick "I reviewed
   the cited evidence", choose Allowed, and record it.

**1:30. Missing-evidence case (60 s).**
1. Load *Gerald P. Vance-Moreau, missing evidence*.
2. **Missing evidence → Check.** The rule-based flags show: last imaging 2024-08-05 is more than
   12 months before filing, no treating source opinion, and the last exam is out of date. The AI
   adds gaps such as an exam without reflex or motor detail and a spine referral that never happened.
3. Scroll to the **draft records request**. Edit one line (for example, add a due date), then click
   **Save letter**.
4. **Triage → Suggest:** *Standard*, with "evidence gaps flagged for development". Override to
   *Senior examiner* to show the required reason box. Record the override.

**2:30. Accountability (30 s).**
1. **Audit trail.** AI events show the model, prompt version, and citation counts. Human events show
   uploads, citation views, the letter edit, the override, and the decision. Click **Export audit
   trail (JSON)**.
2. **Pilot metrics.** Show the override rate, the unverified-citation rate, intake-to-decision time,
   and the AI listing call vs examiner decision table. Toggle "Include seeded demo history" to show
   only this session's claims.

---

## Quality

- `make test`: pytest for the citation verifier, PDF page extraction, the Blue Book chunker and CAL
  parser, queue and missing-evidence rules, LLM retry and validation, and an end-to-end intake →
  summary → verification → audit test. All tests use a `FakeProvider` and never call the network.
- `make eval`: runs the real pipeline on all synthetic cases in a throwaway DB. It reports citation
  verification rate, listing call vs expected, triage vs expected, CAL detection, and rule-flag
  recall, and writes JSON to `backend/eval/results/`. LLM output varies, so expect occasional
  variation on borderline cases.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `openai` | Provider adapter (`openai`, or `fake` for tests) |
| `OPENAI_API_KEY` | – | Required for `openai` |
| `OPENAI_MODEL` | `gpt-4.1` | Chat model; needs Structured Outputs support |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Listing and CAL retrieval embeddings. Re-run `make ingest` after changing it. |
| `IMAGING_RECENCY_MONTHS` / `STALE_RECORD_MONTHS` | `12` | Missing-evidence rule thresholds |
| `VERIFY_THRESHOLD` | `0.85` | Fuzzy match threshold for citation verification |

## Limits (this is a demo MVP)

- One hardcoded demo examiner and no authentication. SQLite with local file storage.
- PDFs must have a text layer (no OCR).
- Listing scope is 1.15 to 1.23. Retrieval returns the top 3 listings.
- Not for real PHI. Do not upload real medical records.
