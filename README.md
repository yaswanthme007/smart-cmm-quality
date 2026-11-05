# Smart CMM Quality Alert and Action Tracking System

Sakthi Hackathon 2.0, Round 2 — PS-011: Real-Time CMM Quality Dashboard with Automatic
Non-Conformance Alerts. Team Xyrus (SKH2-2026-00196), Chennai Institute of Technology.

A vendor-neutral **action layer** on top of CMM software. It reads the result files CMMs already
write (CSV / XLSX / CALYPSO-style table files / AQDEF subset), classifies every characteristic as
**OK / Marginal / Not OK**, alerts the owner of the machine or process within seconds, escalates
if nobody responds, tracks the corrective action to a verified close, and measures every step.

> **Demo data only.** All parts, limits, machines and measurements in this repository are
> synthetic. No real plant data is included.

## The closed loop

```
CMM result file → ingest → classify → NC + alert (in-app + email) → escalate if unacknowledged
               → acknowledge → containment / root cause / action / evidence → verify → closed
```

Every step is time-stamped; the dashboard (inspected / OK / Not OK, OK%, alert generation time,
open / pending / closed actions, closure lead time, trends) is computed from those events.

## Honesty notes

- Near-real-time, file-triggered: no live connection to a CMM controller.
- Aligned with ISA-18.2 alarm principles, ISO 14253-1 decision-rule ideas and IATF 16949
  corrective-action practice — not certified against them.
- Vendor file formats are implemented from public documentation, not vendor certification.
- Demo escalation timers are shortened (seconds instead of minutes).
- AI is optional (`AI_ENABLED=false` by default) and never sits in the alert path.

## Stack

Python 3.12 + FastAPI, PostgreSQL (LISTEN/NOTIFY, transactional outbox, append-only audit log),
React + TypeScript + Vite, Tailwind + shadcn/ui, TanStack Query, Apache ECharts, Docker Compose,
Mailpit for demo email. Rationale for each choice: `docs/BUILD_SPEC.md` Section 6.

## Quick start

_Filled in as the build progresses (Phase 0: `make up`, then open the web app and `/api/docs`)._

## Documentation

- [`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) — build specification (source of truth)
- [`CLAUDE.md`](CLAUDE.md) — working rules for Claude Code

## License

MIT — see [LICENSE](LICENSE).
