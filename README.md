# Smart CMM Quality Alert and Action Tracking System

Sakthi Hackathon 2.0, Round 2 — PS-011: Real-Time CMM Quality Dashboard with Automatic
Non-Conformance Alerts. Team Xyrus (SKH2-2026-00196), Chennai Institute of Technology.

A vendor-neutral **action layer** on top of CMM software. It reads the result files CMMs already
write (CSV / XLSX / CALYPSO-style table files / AQDEF subset / PDF tables), classifies every
characteristic as **OK / Marginal / Not OK**, alerts the owner of the machine within seconds,
escalates if nobody responds, tracks the corrective action to a verified close, and measures every
step.

> **Demo data only.** All parts, limits, machines and measurements in this repository are
> synthetic. No real plant data is included.

## The closed loop

```
CMM result file → ingest → classify → NC + alert (in-app + email) → escalate if unacknowledged
               → acknowledge → containment / root cause / action / evidence → verify → closed
```

Every step is time-stamped; the dashboard (inspected / OK / Not OK, OK %, alert generation time,
open / pending / closed actions, closure lead time, trends, Pareto, SPC) is computed from those
events. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start

Requirements: Docker with Compose, `make`, [`uv`](https://docs.astral.sh/uv/), Node 24.

```bash
cp .env.example .env          # then set the secrets (make up does this copy if missing)
make up                       # db, mailpit, api, worker, web
make demo-reset               # demo masters + 30 days synthetic history + live-demo state
make demo-drop                # drops DC101_SN0457_chr.txt (Not OK) into the CMM-01 inbox
```

| What | URL |
|---|---|
| Web app | http://localhost:5173 |
| API docs (OpenAPI) | http://localhost:8000/api/docs |
| Mailpit (demo email) | http://localhost:8025 |

Demo users (password = `DEMO_USER_PASSWORD` in `.env`): `inspector`, `owner.vmc02`, `owner.hmc01`,
`supervisor`, `qhead`, `admin`, `viewer` — all `@demo.local`. The login page has a picker.

## Commands

| Command | Does |
|---|---|
| `make up` / `make down` / `make logs` | start / stop / follow the stack |
| `make migrate` | apply Alembic migrations |
| `make seed` | demo masters, users, mapping profiles, settings |
| `make demo-reset` | wipe and reseed the demo storyline (≈20 s) |
| `make demo-drop` | live demo step: Not OK file into the watched folder |
| `make gen` | synthetic report files into `samples/` (CSV, CALYPSO-style, AQDEF-subset) |
| `make test` / `make lint` / `make fmt` | backend pytest + frontend Vitest / ruff + oxlint + tsc / format |
| `make e2e` | Playwright closed-loop smoke test against the running stack |
| `make bench` | measure the Section 17 targets, writes `docs/BENCHMARKS.md` |

## Validation

- Golden tests: classification (Section 9.3), SPC (12.4), KPIs (13), adapters (CALYPSO, AQDEF).
- Property tests for limit logic (hypothesis).
- Integration tests: upload → NC → alert → outbox → Mailpit → acknowledge → verify → closed → KPIs.
- Playwright: Not OK upload → live toast for the owner → corrective action → verified and closed.
- Measured numbers: [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## Honesty notes

- Near-real-time, file-triggered: no live connection to a CMM controller.
- Aligned with ISA-18.2 alarm principles, ISO 14253-1 decision-rule ideas and IATF 16949
  corrective-action practice — not certified against them.
- Vendor file formats are implemented from public documentation, not vendor certification.
- Demo escalation timers are shortened (60 s / 120 s instead of minutes).
- AI is optional (`AI_ENABLED=false` by default) and never classifies, alerts or escalates.
- Assumptions not yet confirmed with the plant are listed in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Documentation

- [`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) — build specification (source of truth)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, critical path, layout
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — implementation choices and assumptions
- [`docs/KPI_DEFINITIONS.md`](docs/KPI_DEFINITIONS.md) — K1–K6
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — the 5-minute video
- [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) — measured performance

## License

MIT — see [LICENSE](LICENSE).
