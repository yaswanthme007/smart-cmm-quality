"""Tolerance classification engine (Section 9). Pure functions, no I/O.

- All arithmetic in Decimal, actual quantized to the characteristic's decimals (ROUND_HALF_EVEN).
- Limits are inclusive: a value exactly on a limit is conforming.
- Guard band g = W x guard_band_pct / 100; in tolerance and strictly closer than g to a limit
  -> MARGINAL.
- Part result = worst characteristic result (NOK > MARGINAL > OK).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from app.models.enums import CharKind, Result, ToleranceType

DEFAULT_GUARD_BAND_PCT = Decimal(10)
SUSPECT_FACTOR = Decimal(10)
_RANK = {Result.OK: 0, Result.MARGINAL: 1, Result.NOK: 2}


@dataclass(frozen=True)
class Limits:
    tolerance_type: ToleranceType
    nominal: Decimal | None
    usl: Decimal | None
    lsl: Decimal | None
    decimals: int = 3
    kind: CharKind = CharKind.DIMENSION
    guard_band_pct: Decimal = DEFAULT_GUARD_BAND_PCT
    reference_width: Decimal | None = None  # LOWER_ONLY: configured width for the guard band
    expanded_uncertainty: Decimal | None = None


@dataclass(frozen=True)
class Classification:
    result: Result
    actual: Decimal
    deviation: Decimal | None
    tolerance_used_pct: Decimal | None
    is_suspect: bool
    reason: str | None = None
    over_limit: Decimal | None = None  # signed amount beyond the violated limit (NOK only)


def quantize(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)


def tolerance_zone(limits: Limits) -> tuple[Decimal | None, Decimal | None]:
    """(low, high) of the tolerance zone used for width and midpoint."""
    if limits.tolerance_type == ToleranceType.BILATERAL:
        return limits.lsl, limits.usl
    if limits.tolerance_type == ToleranceType.UPPER_ONLY:
        if limits.usl is None:
            return None, None
        if limits.reference_width is not None:
            return limits.usl - limits.reference_width, limits.usl
        return Decimal(0), limits.usl  # natural zero (flatness, position, runout)
    if limits.lsl is None or limits.reference_width is None:
        return limits.lsl, None
    return limits.lsl, limits.lsl + limits.reference_width


def tolerance_width(limits: Limits) -> Decimal | None:
    low, high = tolerance_zone(limits)
    if low is None or high is None:
        return None
    return high - low


def classify(actual: Decimal, limits: Limits, *, uncertainty_rule: bool = False) -> Classification:
    x = quantize(Decimal(actual), limits.decimals)
    usl = limits.usl if limits.tolerance_type != ToleranceType.LOWER_ONLY else None
    lsl = limits.lsl if limits.tolerance_type != ToleranceType.UPPER_ONLY else None

    width = tolerance_width(limits)
    g = width * limits.guard_band_pct / 100 if width is not None else Decimal(0)
    deviation = x - limits.nominal if limits.nominal is not None else None

    used_pct = None
    low, high = tolerance_zone(limits)
    if width and low is not None and high is not None:
        mid = (low + high) / 2
        used_pct = quantize(abs(x - mid) / (width / 2) * 100, 2)

    suspect = limits.kind == CharKind.GEOMETRIC and x < 0
    if width and deviation is not None and abs(deviation) > SUSPECT_FACTOR * width:
        suspect = True

    reason = None
    over = None
    if usl is not None and x > usl:
        result, over = Result.NOK, x - usl
    elif lsl is not None and x < lsl:
        result, over = Result.NOK, x - lsl
    elif (usl is not None and usl - x < g) or (lsl is not None and x - lsl < g):
        result, reason = Result.MARGINAL, "within guard band"
    else:
        result = Result.OK

    # ISO 14253-1 idea: stringent acceptance shrinks the zone by U at each limit.
    u = limits.expanded_uncertainty
    in_uncertainty_zone = bool(u) and (
        (usl is not None and x > usl - u) or (lsl is not None and x < lsl + u)
    )
    if uncertainty_rule and result != Result.NOK and in_uncertainty_zone:
        result, reason = Result.MARGINAL, "within measurement uncertainty"

    if suspect:
        reason = "possible probing/entry error, re-measure"
    return Classification(result, x, deviation, used_pct, suspect, reason, over)


def worst(results: Iterable[Result]) -> Result:
    """Part result: the worst characteristic result; OK when there are none."""
    return max(results, key=_RANK.__getitem__, default=Result.OK)


def limits_from_tolerances(
    nominal: Decimal | None,
    upper_tol: Decimal | None,
    lower_tol: Decimal | None,
    usl: Decimal | None,
    lsl: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Absolute limits from either absolute values or nominal + tolerances (lower_tol <= 0)."""
    if usl is None and nominal is not None and upper_tol is not None:
        usl = nominal + upper_tol
    if lsl is None and nominal is not None and lower_tol is not None:
        lsl = nominal + lower_tol
    return usl, lsl
