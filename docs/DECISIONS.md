# Decisions ("why this, not that")

The decision records D1–D24 are in [`BUILD_SPEC.md` Section 6](BUILD_SPEC.md#6-technology-choices-and-decision-records-why-this-not-that)
and are followed as written. This file records **what the build actually did** where it had to be
more specific than the spec, so nobody presents an assumption as a fact.

## Versions pinned at build time (lockfiles: `backend/uv.lock`, `frontend/package-lock.json`)

Python 3.12, FastAPI 0.162, SQLAlchemy 2.1, Alembic 1.20, psycopg 3.3, PostgreSQL 17.6,
React 19, React Router 7, TanStack Query 5, Tailwind CSS 4, Apache ECharts 6, Vite 8, Vitest 4,
Playwright 1.65, Node 24 LTS, uv 0.13.7, Mailpit 1.27.

## Implementation choices within the spec

| Topic | What we did | Why |
|---|---|---|
| UI kit (D9) | Small hand-written shadcn-style components in `components/ui.tsx` instead of the shadcn CLI | Same look and Tailwind approach, fewer generated files to explain |
| Frontend lint | `oxlint` (Vite template default) + `tsc` | Fast; `make lint` fails on warnings |
| Similar NCs (Section 19) | TF-IDF + cosine implemented with numpy, not scikit-learn | Same textbook method, no extra 100 MB dependency; runs locally |
| AI provider (Section 19) | Groq (official `groq` Python SDK), model from `AI_MODEL` (default `llama-3.3-70b-versatile`), `temperature=0`, JSON output; the PDF's text layer is extracted locally and only that text is sent; every returned number is checked against the PDF text and flagged if not found verbatim | Team choice (fast, low cost); text-only keeps what leaves the plant small and checkable. Scanned image-only PDFs are refused (no OCR) |
| PDF reports | Deterministic `pdfplumber` table extraction first; AI only if that fails and AI is on; AI rows wait in `NEEDS_CONFIRMATION` and are classified only after a person confirms | Spec Section 19 safety rule |
| Duplicate files | Unique SHA-256 only among non-FAILED reports | A file that failed (e.g. wrong mapping) can be retried after fixing the profile; successful re-uploads still return 409 |
| Characteristic names | Stored without the nominal ("Bearing bore Ø"); alert text renders "Bearing bore Ø72.000 +0.030/-0.000" | Matches Section 10.3 alert format |
| Part number matching | Exact, then ignoring separators (`DC101` in a filename = `DC-101`) | File names usually drop the hyphen |
| Extra columns | `characteristics.reference_width` (LOWER_ONLY guard band), `measurements.char_no/char_name` (unknown characteristics), `outbox.alert_id` (email time per alert), `nonconformances.warnings` (no-owner warning), `spc_signals.in_control_streak` (clear after 9 points) | Needed to implement rules the spec states |
| SPC evaluation | Runs inside the ingest transaction for the touched streams, not in a separate worker loop | Deterministic, cheap at plant volumes, and the SPC alert is committed with the data that caused it |
| Baseline | Created automatically from the first 25 conforming readings of a stream (audited as SYSTEM); recalculation is Quality Head only | Section 12.1 |
| Synthetic history | Inserted through the real pipeline with a shifted clock (`app/core/clock.py`); back-dated alerts queue no emails | Alert times in history are the real processing times of the seed run, never typed-in numbers |
| Recurrence | Not OK characteristics that match an open NC (same part + machine + characteristic, within the window) link to it; others in the same report open one new NC | Section 10.1 rules 2 and 3 |
| Escalation base time | `detected_at`; level 2 also implies level 1 | Section 10.4 |
| Test database | `<db>_test` on the same server, schema rebuilt from migrations each test session | Tests exercise the real migrations and the audit trigger |

## ASSUMPTIONS to validate with Sakthi

| Assumption | Where | How to change |
|---|---|---|
| Three 8-hour shifts A 06–14, B 14–22, C 22–06 IST | `settings.shifts` | Settings value |
| Escalation plant timers (10/30, 20/60, 30/120 min) | `settings.escalation` | Settings page |
| CALYPSO `_chr.txt` columns (`id`, `actual`, `nominal`, `uppertol`, `lowertol`, `comment`) and `_hdr.txt` header fields | `calypso_chr` preset profile | Mapping profile editor; validate with a real file |
| AQDEF fields K2101 nominal, K2110 LSL, K2111 USL, K0004 time, K0010 machine, K0014 part ident; one part per file | `services/adapters/aqdef.py` | Verify against the Q-DAS manual and a real `.dfq` |
| Naive timestamps in files are plant local time (IST) | `services/ingestion/normalize.py` | `PLANT_TZ` |
| Demo owners: VMC-02 and OP-20/OP-30 → owner.vmc02; HMC-01 and OP-40 → owner.hmc01; supervisor for all | `seed/masters.py` | Masters / ownership rules |
