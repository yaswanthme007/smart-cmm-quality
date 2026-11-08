"""Validation helpers (Section 8.1 step 7)."""

from typing import Any

from app.models import Characteristic
from app.models.enums import ToleranceType
from app.schemas.ingest import RawRecord
from app.services.classification import limits_from_tolerances, quantize


def limit_mismatch(rec: RawRecord, char: Characteristic) -> dict[str, Any] | None:
    """Warn when the report's printed nominal/limits differ from the master (drawing revision risk).

    Master data is the source of truth (Section 6 D12); a mismatch never changes the verdict.
    """
    usl, lsl = limits_from_tolerances(rec.nominal, rec.upper_tol, rec.lower_tol, rec.usl, rec.lsl)
    d = char.decimals
    diffs = []

    def differs(report_value: Any, master_value: Any) -> bool:
        if report_value is None or master_value is None:
            return False
        return quantize(report_value, d) != quantize(master_value, d)

    if differs(rec.nominal, char.nominal) and char.tolerance_type == ToleranceType.BILATERAL:
        diffs.append(f"nominal {rec.nominal} vs master {char.nominal}")
    if char.tolerance_type != ToleranceType.LOWER_ONLY and differs(usl, char.usl):
        diffs.append(f"USL {usl} vs master {char.usl}")
    if char.tolerance_type != ToleranceType.UPPER_ONLY and differs(lsl, char.lsl):
        diffs.append(f"LSL {lsl} vs master {char.lsl}")
    if not diffs:
        return None
    return {
        "code": "LIMIT_MISMATCH",
        "char_no": rec.char_no,
        "message": f"{rec.char_no}: report limits differ from master ({'; '.join(diffs)}); "
        "master limits used - check drawing revision",
    }
