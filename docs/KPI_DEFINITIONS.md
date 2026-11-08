# KPI definitions

Every KPI is computed by `backend/app/services/kpi.py` from stored events; nobody types a number.
The same functions feed the dashboard, the tooltips, `/api/kpi/*` and the Excel export, so the
workbook always matches the screen.

**Filters** (all KPIs): date range (plant-local IST days, `date_to` inclusive), part, machine,
process, shift. Report KPIs use the report's `measured_at` (falling back to `received_at`); NC
KPIs use `detected_at`; alert KPIs use the alert's `created_at`. Only reports with status
`INGESTED` count (FAILED and NEEDS_CONFIRMATION do not).

| ID | KPI | Definition | Endpoint |
|---|---|---|---|
| K1 | Inspected / OK / Not OK | Count of inspection reports (parts). OK = part result OK or MARGINAL; Not OK = part result NOK; Marginal shown as a sub-count | `/api/kpi/summary` → `k1` |
| K2 | OK % / Not OK % | OK ÷ Inspected × 100 and Not OK ÷ Inspected × 100, rounded to 1 decimal (`null` when nothing inspected). Characteristic-level Not OK % also returned | `k2` |
| K3 | Alert generation time | For every Not OK result (NOK and RECURRENCE alerts): `alert.created_at − report.received_at` in ms. Median, p95, max; the full list at `/api/kpi/alert-times`. Email time `outbox.sent_at − received_at` reported separately | `k3`, `/api/kpi/alert-times` |
| K3b | Report latency | `received_at − measured_at` (only when the file carried a measurement time) | `k3b` |
| K4 | Open / Pending / Closed actions | Open = OPEN + ACKNOWLEDGED; Pending = IN_PROGRESS + PENDING_VERIFICATION; Closed = CLOSED. Cancelled, Overdue (target date passed, not closed) and escalated-open shown separately | `k4` |
| K5 | Closure lead time | `closed_at − detected_at` per closed NC: median and p90 (hours); % closed by target date; acknowledgement time `acknowledged_at − detected_at` (median minutes) | `k5` |
| K6 | Trends | Daily / weekly inspected and Not OK % (overall, by machine, part or process); Pareto of Not OK characteristics with cumulative %; open-NC ageing buckets 0–1 d, 1–3 d, 3–7 d, > 7 d | `/api/kpi/trends`, `/api/kpi/pareto`, `/api/kpi/ageing`, `/api/kpi/by` |

**Golden fixture** (`backend/tests/integration/test_kpi.py`): 10 reports (7 OK, 1 MARGINAL,
2 NOK) → Inspected 10, OK 8, Not OK 2, OK % 80.0, Not OK % 20.0.

**Percentiles** use PostgreSQL `percentile_cont` (linear interpolation).
**Shifts** come from `settings.shifts` (default A 06:00, B 14:00, C 22:00 IST; an assumption to
confirm with the plant).
