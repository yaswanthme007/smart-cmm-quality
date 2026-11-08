"""Excel and PDF exports (Section 14). Numbers come from the same KPI service as the dashboard,
so an exported workbook always matches what is on screen."""

import io
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from app.services import kpi

DEMO_NOTE = "DEMO DATA: synthetic prototype data, not real plant data."
HEADER_FILL = PatternFill("solid", fgColor="1E293B")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _sheet(ws: Worksheet, title: str, headers: list[str], rows: list[list[Any]]) -> None:
    ws.title = title[:31]
    ws.append([DEMO_NOTE])
    ws["A1"].font = Font(italic=True, color="B45309")
    ws.append([])
    ws.append(headers)
    for cell in ws[3]:
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(wrap_text=True)
    for row in rows:
        ws.append(row)
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if i - 1 < len(r)] + [8])
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)
    ws.freeze_panes = "A4"


def filter_text(f: kpi.KpiFilter) -> str:
    parts = [f"{k}={v}" for k, v in vars(f).items() if v is not None]
    return ", ".join(parts) or "none"


def kpi_workbook(session: Session, f: kpi.KpiFilter) -> bytes:
    s = kpi.summary(session, f)
    wb = Workbook()
    rows = [
        ["Filters", filter_text(f), ""],
        ["Generated (UTC)", datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"), ""],
        ["K1", "Inspected", s["k1"]["inspected"]],
        ["K1", "OK (incl. marginal)", s["k1"]["ok"]],
        ["K1", "of which marginal", s["k1"]["marginal"]],
        ["K1", "Not OK", s["k1"]["nok"]],
        ["K2", "OK %", s["k2"]["ok_pct"]],
        ["K2", "Not OK %", s["k2"]["nok_pct"]],
        ["K2", "Characteristic Not OK %", s["k2"]["characteristic_nok_pct"]],
        ["K3", "Alert generation time median (ms)", s["k3"]["median_ms"]],
        ["K3", "Alert generation time p95 (ms)", s["k3"]["p95_ms"]],
        ["K3", "Alert generation time max (ms)", s["k3"]["max_ms"]],
        ["K3", "Email time median (ms)", s["k3"]["email_median_ms"]],
        ["K3b", "Report latency median (s)", s["k3b"]["median_s"]],
        ["K4", "Open actions", s["k4"]["open"]],
        ["K4", "Pending actions", s["k4"]["pending"]],
        ["K4", "Closed actions", s["k4"]["closed"]],
        ["K4", "Cancelled", s["k4"]["cancelled"]],
        ["K4", "Overdue", s["k4"]["overdue"]],
        ["K5", "Closure lead time median (h)", s["k5"]["median_h"]],
        ["K5", "Closure lead time p90 (h)", s["k5"]["p90_h"]],
        ["K5", "Closed by target date %", s["k5"]["closed_on_time_pct"]],
        ["K5", "Acknowledgement time median (min)", s["k5"]["ack_median_min"]],
    ]
    _sheet(wb.active, "Summary", ["KPI", "Measure", "Value"], rows)

    trend = kpi.trends(session, f, "day", "none")
    _sheet(
        wb.create_sheet(),
        "Trend by day",
        ["Day", "Inspected", "Not OK", "Marginal", "Not OK %"],
        [[t["bucket"], t["inspected"], t["nok"], t["marginal"], t["nok_pct"]] for t in trend],
    )
    by_machine = kpi.trends(session, f, "day", "machine")
    _sheet(
        wb.create_sheet(),
        "Trend by machine",
        ["Day", "Machine", "Inspected", "Not OK", "Not OK %"],
        [[t["bucket"], t["group"], t["inspected"], t["nok"], t["nok_pct"]] for t in by_machine],
    )
    by_part = kpi.trends(session, f, "day", "part")
    _sheet(
        wb.create_sheet(),
        "Trend by part",
        ["Day", "Part", "Inspected", "Not OK", "Not OK %"],
        [[t["bucket"], t["group"], t["inspected"], t["nok"], t["nok_pct"]] for t in by_part],
    )
    pareto = kpi.pareto(session, f, limit=100)
    _sheet(
        wb.create_sheet(),
        "Pareto",
        ["Part", "Characteristic", "Name", "Not OK count", "Cumulative %"],
        [[p["part_no"], p["char_no"], p["name"], p["count"], p["cumulative_pct"]] for p in pareto],
    )
    ageing = kpi.ageing(session, f)
    _sheet(
        wb.create_sheet(),
        "NC ageing",
        ["Age", "Open NCs"],
        [[a["bucket"], a["count"]] for a in ageing],
    )
    times = kpi.alert_times(session, f, limit=5000)
    _sheet(
        wb.create_sheet(),
        "Alert times",
        ["NC", "Kind", "Received", "Alert created", "Generation ms", "Email ms"],
        [
            [
                t["nc_no"],
                t["kind"],
                t["source_received_at"],
                t["created_at"],
                t["generation_ms"],
                t["email_ms"],
            ]
            for t in times
        ],
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def ncs_workbook(rows: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    headers = [
        "NC",
        "Status",
        "Severity",
        "Part",
        "Machine",
        "Characteristics",
        "Owner",
        "Detected",
        "Acknowledged",
        "Target date",
        "Closed",
        "Escalation",
        "Recurrences",
        "Overdue",
        "Root cause (6M)",
        "Root cause",
        "Corrective action",
    ]
    keys = [
        "nc_no",
        "status",
        "severity",
        "part_no",
        "machine_code",
        "characteristics",
        "owner_name",
        "detected_at",
        "acknowledged_at",
        "target_date",
        "closed_at",
        "escalation_level",
        "recurrence_count",
        "overdue",
        "root_cause_category",
        "root_cause",
        "corrective_action",
    ]
    data = []
    for r in rows:
        line = []
        for k in keys:
            v = r.get(k)
            if isinstance(v, list):
                v = ", ".join(v)
            elif hasattr(v, "isoformat"):
                v = v.isoformat()
            elif hasattr(v, "value"):
                v = v.value
            line.append(v)
        data.append(line)
    _sheet(wb.active, "Non-conformances", headers, data)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_pdf(report: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        title=f"Inspection report {report['report_no']}",
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph(f"Inspection report {report['report_no']}", styles["Title"]),
        Paragraph(DEMO_NOTE, styles["Italic"]),
        Spacer(1, 4 * mm),
    ]
    meta = [
        ["Part", f"{report.get('part_no') or '-'} {report.get('part_name') or ''}"],
        ["Serial", report.get("serial_no") or "-"],
        [
            "Machine / process",
            f"{report.get('machine_code') or '-'} / {report.get('process_code') or '-'}",
        ],
        ["Measured at (UTC)", str(report.get("measured_at") or "-")],
        ["Received at (UTC)", str(report.get("received_at") or "-")],
        [
            "Result",
            f"{report.get('part_result')} (Not OK {report.get('nok_count')}, marginal {report.get('marginal_count')})",
        ],
        ["Non-conformance", ", ".join(report.get("nc_nos") or []) or "-"],
    ]
    t = Table(meta, colWidths=[45 * mm, 130 * mm])
    t.setStyle(
        TableStyle(
            [("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9)]
        )
    )
    story += [t, Spacer(1, 5 * mm)]
    rows = [["Char", "Name", "Nominal", "LSL", "USL", "Actual", "Dev", "Result"]]
    colours = []
    for i, m in enumerate(report.get("measurements", []), start=1):
        rows.append(
            [
                m["char_no"],
                (m.get("char_name") or "")[:28],
                _f(m.get("nominal")),
                _f(m.get("lsl")),
                _f(m.get("usl")),
                _f(m.get("actual")),
                _f(m.get("deviation")),
                {"OK": "OK", "MARGINAL": "MARGINAL", "NOK": "NOT OK"}[m["result"]]
                + (" *" if m.get("is_suspect") else ""),
            ]
        )
        colour = {
            "OK": colors.HexColor("#DCFCE7"),
            "MARGINAL": colors.HexColor("#FEF3C7"),
            "NOK": colors.HexColor("#FEE2E2"),
        }[m["result"]]
        colours.append(("BACKGROUND", (7, i), (7, i), colour))
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (2, 1), (6, -1), "RIGHT"),
                *colours,
            ]
        )
    )
    story += [
        table,
        Spacer(1, 3 * mm),
        Paragraph("* suspect value: possible probing/entry error, re-measure.", styles["Italic"]),
    ]
    warnings = report.get("warnings") or []
    if warnings:
        story.append(Paragraph("Warnings", styles["Heading3"]))
        for w in warnings:
            story.append(Paragraph(f"{w.get('code')}: {w.get('message')}", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def _f(v: Any) -> str:
    if v is None:
        return "-"
    return f"{float(v):.3f}"
