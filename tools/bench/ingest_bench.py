"""Benchmark the Section 17 targets against the RUNNING stack (`make up`). SYNTHETIC DATA.

Measures, with real timestamps (never quotes targets as results):
  1. ingest -> in-app alert for a 100-characteristic report (alert.generation_ms, p50/p95)
  2. SSE delivery: upload start -> alert.created event received by the owner's stream
  3. email handed to SMTP: outbox sent_at - file received (from /kpi/alert-times)
  4. dashboard summary latency (GET /kpi/summary), optionally after bulk-loading N reports
  5. watched-folder pickup: file dropped in data/inbox/CMM-02 -> report visible in the API

Usage (repo root):
  make bench                       # default 30 uploads
  cd backend && uv run python ../tools/bench/ingest_bench.py --uploads 50 --volume 20000

`--volume` bulk-inserts synthetic reports straight into the database to test dashboard speed at
scale; run `make demo-reset` afterwards to return to the demo storyline.
Results are printed and written to docs/BENCHMARKS.md.
"""

import argparse
import json
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

BENCH_PART = "BN-900"
N_CHARS = 100


def env_value(key: str) -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} missing in .env")


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def login(base: str, user: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base, timeout=30)
    r = client.post("/api/auth/login", json={"email": f"{user}@demo.local", "password": password})
    r.raise_for_status()
    return client


def ensure_bench_part(admin: httpx.Client) -> None:
    """A synthetic 100-characteristic part (BN-900) so reports match Section 17's size."""
    parts = {p["part_no"]: p for p in admin.get("/api/parts").json()}
    if BENCH_PART in parts:
        return
    part = admin.post(
        "/api/parts",
        json={
            "part_no": BENCH_PART,
            "name": "Bench part (demo)",
            "drawing_no": "DEMO-BN900",
            "drawing_rev": "A",
        },
    ).json()
    processes = {p["code"]: p["id"] for p in admin.get("/api/processes").json()}
    for i in range(1, N_CHARS + 1):
        nominal = 10 + i
        admin.post(
            f"/api/characteristics?parent_id={part['id']}",
            json={
                "char_no": f"C-{i:03d}",
                "name": f"Bench feature {i}",
                "tolerance_type": "BILATERAL",
                "nominal": nominal,
                "usl": nominal + 0.05,
                "lsl": nominal - 0.05,
                "classification": "CRITICAL" if i == 1 else "STANDARD",
                "process_id": processes["OP-40"],
            },
        ).raise_for_status()


def bench_csv(serial: int, nok: bool) -> bytes:
    lines = ["Dimension,Description,Nominal,+Tol,-Tol,Measured,Note"]
    for i in range(1, N_CHARS + 1):
        nominal = 10 + i
        actual = nominal + (0.061 if (nok and i == 1) else 0.004 * ((serial + i) % 5 - 2))
        lines.append(
            f"C-{i:03d},Bench feature {i},{nominal:.3f},0.050,-0.050,{actual:.3f},bench {serial} {uuid.uuid4().hex[:6]}"
        )
    return ("\n".join(lines) + "\n").encode()


class SseListener(threading.Thread):
    """Owner's live stream; records the arrival time of each alert.created by NC id."""

    def __init__(self, base: str, cookies: httpx.Cookies) -> None:
        super().__init__(daemon=True)
        self.base, self.cookies = base, cookies
        self.arrivals: dict[str, float] = {}
        self.ready = threading.Event()

    def run(self) -> None:
        with (
            httpx.Client(base_url=self.base, cookies=self.cookies, timeout=None) as c,
            c.stream("GET", "/api/stream") as r,
        ):
            event = None
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                    if event == "hello":
                        self.ready.set()
                elif line.startswith("data:") and event == "alert.created":
                    data = json.loads(line.split(":", 1)[1])
                    if data.get("nc_id"):
                        self.arrivals.setdefault(data["nc_id"], time.perf_counter())


def cancel_bench_ncs(qhead: httpx.Client) -> None:
    page = qhead.get("/api/ncs?bucket=open&limit=500").json()
    for nc in page["items"]:
        if nc["part_no"] == BENCH_PART:
            qhead.post(
                f"/api/ncs/{nc['id']}/cancel", json={"reason": "benchmark cleanup (synthetic)"}
            )


def bulk_volume(n: int) -> None:
    """Insert n synthetic INGESTED reports directly (dashboard-at-scale test only)."""
    from sqlalchemy import text

    from app.core.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO inspection_reports (id, report_no, part_id, machine_id, process_id, serial_no,
                    measured_at, received_at, ingested_at, source, sha256, part_result, nok_count,
                    marginal_count, status, warnings, created_at, updated_at)
                SELECT gen_random_uuid(), 'BULK-' || g, p.id, m.id, m.process_id, 'B' || g,
                    now() - (g || ' minutes')::interval, now() - (g || ' minutes')::interval, now(),
                    'UPLOAD', md5('bulk' || g || random()), CASE WHEN g % 25 = 0 THEN 'NOK' ELSE 'OK' END,
                    CASE WHEN g % 25 = 0 THEN 1 ELSE 0 END, 0, 'INGESTED', '[]'::jsonb, now(), now()
                FROM generate_series(1, :n) g
                CROSS JOIN LATERAL (SELECT id FROM parts ORDER BY part_no LIMIT 1) p
                CROSS JOIN LATERAL (SELECT id, process_id FROM machines ORDER BY code LIMIT 1) m
                """
            ),
            {"n": n},
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--uploads", type=int, default=30)
    ap.add_argument("--volume", type=int, default=0, help="bulk-insert this many reports first")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "BENCHMARKS.md")
    args = ap.parse_args()
    password = env_value("DEMO_USER_PASSWORD")

    admin = login(args.base, "admin", password)
    ensure_bench_part(admin)
    qhead = login(args.base, "qhead", password)
    cancel_bench_ncs(qhead)
    inspector = login(args.base, "inspector", password)
    owner = login(args.base, "owner.hmc01", password)
    machines = {m["code"]: m["id"] for m in inspector.get("/api/machines").json()}

    sse = SseListener(args.base, owner.cookies)
    sse.start()
    sse.ready.wait(10)

    gen_ms, sse_ms, http_ms = [], [], []
    for k in range(args.uploads):
        serial = int(time.time() * 1000) % 10_000_000 + k
        content = bench_csv(serial, nok=True)
        t0 = time.perf_counter()
        r = inspector.post(
            "/api/reports/upload",
            files={"file": (f"BN900_SN{serial}.csv", content, "text/csv")},
            data={"machine_id": machines["HMC-01"]},
        )
        http_ms.append((time.perf_counter() - t0) * 1000)
        body = r.json()
        if r.status_code != 201 or not body.get("nc_ids"):
            print("upload failed:", r.status_code, str(body)[:200])
            continue
        nc_id = body["nc_ids"][0]
        deadline = time.perf_counter() + 5
        while nc_id not in sse.arrivals and time.perf_counter() < deadline:
            time.sleep(0.005)
        if nc_id in sse.arrivals:
            sse_ms.append((sse.arrivals[nc_id] - t0) * 1000)
        alert = owner.get("/api/alerts?mine=true&limit=5").json()["items"]
        match = next((a for a in alert if a["nc_id"] == nc_id), None)
        if match and match["generation_ms"] is not None:
            gen_ms.append(match["generation_ms"])
        qhead.post(f"/api/ncs/{nc_id}/cancel", json={"reason": "benchmark cleanup (synthetic)"})

    time.sleep(6)  # let the worker hand emails to SMTP
    times = qhead.get("/api/kpi/alert-times?limit=5000").json()
    email_ms = [
        t["email_ms"] for t in times if t["email_ms"] is not None and "BN-900" in t["title"]
    ][: args.uploads]

    if args.volume:
        bulk_volume(args.volume)
    summary_ms = []
    for _ in range(10):
        t0 = time.perf_counter()
        qhead.get("/api/kpi/summary").raise_for_status()
        summary_ms.append((time.perf_counter() - t0) * 1000)
    inspected = qhead.get("/api/kpi/summary").json()["k1"]["inspected"]

    # Watched folder pickup (CMM-02 inbox; generic CSV preset; machine from... the CMM-02 profile
    # takes the machine from the upload form, so use the bench part via a header-line-free CSV and
    # measure only the time until a report row (OK or FAILED) appears).
    inbox = ROOT / "data" / "inbox" / "CMM-02"
    inbox.mkdir(parents=True, exist_ok=True)
    name = f"BN900_SN{int(time.time())}.csv"
    before = qhead.get("/api/reports?limit=1").json()["total"]
    t0 = time.perf_counter()
    (inbox / name).write_bytes(bench_csv(1, nok=False))
    folder_s = None
    while time.perf_counter() - t0 < 30:
        if qhead.get("/api/reports?limit=1").json()["total"] > before:
            folder_s = time.perf_counter() - t0
            break
        time.sleep(0.2)

    rows = [
        (
            "Ingest -> in-app alert (generation_ms), 100-char report",
            "p95 < 2 s",
            f"p50 {pct(gen_ms, 0.5):.0f} ms, p95 {pct(gen_ms, 0.95):.0f} ms, max {max(gen_ms, default=float('nan')):.0f} ms (n={len(gen_ms)})",
        ),
        (
            "Upload HTTP round trip, 100-char report",
            "-",
            f"p50 {pct(http_ms, 0.5):.0f} ms, p95 {pct(http_ms, 0.95):.0f} ms (n={len(http_ms)})",
        ),
        (
            "Upload start -> SSE alert.created at owner's stream",
            "< 1 s after commit",
            f"p50 {pct(sse_ms, 0.5):.0f} ms, p95 {pct(sse_ms, 0.95):.0f} ms (n={len(sse_ms)})",
        ),
        (
            "Email handed to SMTP (sent_at - received_at)",
            "< 10 s",
            f"p50 {pct(email_ms, 0.5) / 1000:.1f} s, p95 {pct(email_ms, 0.95) / 1000:.1f} s (n={len(email_ms)})",
        ),
        (
            f"Dashboard summary with {inspected} reports",
            "< 1 s (at 20,000)",
            f"p50 {pct(summary_ms, 0.5):.0f} ms, p95 {pct(summary_ms, 0.95):.0f} ms (n=10)",
        ),
        (
            "Watched-folder pickup (drop -> report stored)",
            "< 5 s after stable",
            f"{folder_s:.1f} s (includes the 2-check stability wait)"
            if folder_s
            else "not observed within 30 s",
        ),
    ]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    md = [
        "# Benchmark results (measured, synthetic data)",
        "",
        f"Run {stamp} on the developer laptop with `docker compose` (single API worker, Vite dev server).",
        "Generated by `tools/bench/ingest_bench.py`. Targets come from BUILD_SPEC Section 17; the",
        "right-hand column is what was actually measured. Re-run before quoting numbers.",
        "",
        "| Measure | Target | Measured |",
        "|---|---|---|",
        *[f"| {a} | {b} | {c} |" for a, b, c in rows],
        "",
    ]
    text_out = "\n".join(md)
    print(text_out)
    args.out.write_text(text_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
