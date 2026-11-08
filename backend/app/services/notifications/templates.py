"""Alert text (Section 10.3). Plain text works in the app, email and any future channel."""

from decimal import Decimal

from app.core.config import get_settings
from app.models.enums import ToleranceType


def fmt(x: Decimal | None, decimals: int = 3) -> str:
    return "-" if x is None else f"{x:.{decimals}f}"


def limits_text(
    name: str,
    tolerance_type: ToleranceType,
    nominal: Decimal | None,
    usl: Decimal | None,
    lsl: Decimal | None,
    decimals: int = 3,
) -> str:
    """e.g. 'Bearing bore Ø72.000 +0.030/-0.000' or 'Flange face flatness ≤ 0.040'."""
    if tolerance_type == ToleranceType.UPPER_ONLY:
        return f"{name} ≤ {fmt(usl, decimals)}"
    if tolerance_type == ToleranceType.LOWER_ONLY:
        return f"{name} ≥ {fmt(lsl, decimals)}"
    sep = "" if name.endswith("Ø") else " "
    if nominal is None or usl is None or lsl is None:
        return f"{name}{sep}{fmt(lsl, decimals)}…{fmt(usl, decimals)}"
    return f"{name}{sep}{fmt(nominal, decimals)} +{fmt(usl - nominal, decimals)}/-{fmt(nominal - lsl, decimals)}"


def over_text(over: Decimal | None, decimals: int = 3) -> str:
    if over is None:
        return ""
    return (
        f" (+{fmt(over, decimals)} over USL)" if over > 0 else f" ({fmt(over, decimals)} under LSL)"
    )


def nc_link(nc_id: object) -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/ncs/{nc_id}"


def nok_alert(
    *,
    prefix: str,
    part_no: str,
    part_name: str,
    serial_no: str | None,
    machine_code: str | None,
    process_text: str | None,
    lines: list[str],
    severity: str,
    nc_no: str,
    nc_id: object,
    extra: list[str] | None = None,
) -> tuple[str, str]:
    """(title, body) for NOK / RECURRENCE alerts."""
    where = " / ".join(p for p in [machine_code, process_text] if p)
    sn = f", SN {serial_no}" if serial_no else ""
    title = f"[{prefix}] {part_no} {part_name}{sn}, {where}"
    body_lines = [
        title,
        *lines,
        f"Severity: {severity} characteristic. {nc_no}. Acknowledge: {nc_link(nc_id)}",
        *(extra or []),
        "Demo data: synthetic prototype.",
    ]
    return title, "\n".join(body_lines)
