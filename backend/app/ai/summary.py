"""Weekly summary (Section 19, COULD). Deterministic template over KPI-service numbers.

Every number comes from the KPI service; no model is involved, so nothing can be invented.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.services import kpi


def weekly_summary(session: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    f = kpi.KpiFilter(date_from=now - timedelta(days=7), date_to=now)
    s = kpi.summary(session, f)
    pareto = kpi.pareto(session, f, limit=3)
    machines = sorted(kpi.by_dimension(session, f, "machine"), key=lambda r: -(r["nok"] or 0))
    k1, k2, k3, k4, k5 = s["k1"], s["k2"], s["k3"], s["k4"], s["k5"]
    lines = [
        f"Week ending {now.date().isoformat()} (demo data).",
        f"{k1['inspected']} parts inspected: {k1['ok']} OK ({k2['ok_pct']}%), {k1['nok']} Not OK "
        f"({k2['nok_pct']}%), {k1['marginal']} marginal.",
    ]
    if machines and machines[0]["nok"]:
        m = machines[0]
        lines.append(
            f"Most Not OK parts on {m['group']}: {m['nok']} of {m['inspected']} ({m['nok_pct']}%)."
        )
    if pareto:
        lines.append(
            "Top Not OK characteristics: "
            + ", ".join(f"{p['label']} ({p['count']})" for p in pareto)
            + "."
        )
    if k3["median_ms"] is not None:
        lines.append(
            f"Alerts reached owners in a median {k3['median_ms']:.0f} ms (p95 {k3['p95_ms']:.0f} ms)."
        )
    lines.append(
        f"Actions: {k4['open']} open, {k4['pending']} pending, {k4['closed']} closed, {k4['overdue']} overdue."
    )
    if k5["median_h"] is not None:
        lines.append(
            f"Median closure lead time {k5['median_h']} h; {k5['closed_on_time_pct']}% closed by target date."
        )
    return {"text": "\n".join(lines), "kpi": s, "generated_at": now.isoformat()}
