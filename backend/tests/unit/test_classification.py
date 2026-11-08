"""Golden cases from Section 9.3 (must pass exactly) and property tests."""

from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.models.enums import CharKind, Result, ToleranceType
from app.services.classification import Limits, classify, limits_from_tolerances, worst

BORE = Limits(ToleranceType.BILATERAL, nominal=D("72.000"), usl=D("72.030"), lsl=D("72.000"))
FLATNESS = Limits(
    ToleranceType.UPPER_ONLY,
    nominal=D("0"),
    usl=D("0.050"),
    lsl=None,
    kind=CharKind.GEOMETRIC,
)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ("72.015", Result.OK),
        ("72.003", Result.OK),  # exactly g from LSL is not "< g"
        ("72.002", Result.MARGINAL),
        ("72.028", Result.MARGINAL),
        ("72.030", Result.MARGINAL),  # on limit = conforming, inside guard band
        ("72.031", Result.NOK),
        ("71.999", Result.NOK),
        ("72.0304", Result.MARGINAL),  # decimals 3 -> 72.030
    ],
)
def test_golden_bearing_bore(actual, expected):
    assert classify(D(actual), BORE).result == expected


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ("0.020", Result.OK),
        ("0.046", Result.MARGINAL),
        ("0.050", Result.MARGINAL),
        ("0.051", Result.NOK),
    ],
)
def test_golden_flatness(actual, expected):
    c = classify(D(actual), FLATNESS)
    assert c.result == expected
    assert not c.is_suspect


def test_golden_flatness_negative_is_suspect():
    assert classify(D("-0.001"), FLATNESS).is_suspect


def test_quantize_half_even():
    assert classify(D("72.0305"), BORE).actual == D("72.030")  # half-even: 0 stays
    assert classify(D("72.0315"), BORE).actual == D("72.032")


def test_deviation_tolerance_used_and_over_limit():
    c = classify(D("72.034"), BORE)
    assert c.result == Result.NOK
    assert c.deviation == D("0.034")
    assert c.over_limit == D("0.004")
    assert c.tolerance_used_pct == D("126.67")  # |72.034 - 72.015| / 0.015 * 100
    assert classify(D("72.015"), BORE).tolerance_used_pct == D("0.00")


def test_suspect_when_deviation_exceeds_ten_tolerance_widths():
    c = classify(D("72.400"), BORE)
    assert c.is_suspect
    assert c.result == Result.NOK
    assert "re-measure" in (c.reason or "")


def test_guard_band_override():
    tight = Limits(
        ToleranceType.BILATERAL, D("72"), D("72.030"), D("72.000"), guard_band_pct=D("20")
    )
    assert classify(D("72.005"), tight).result == Result.MARGINAL  # g = 0.006
    assert classify(D("72.005"), BORE).result == Result.OK  # g = 0.003


def test_lower_only_uses_reference_width():
    lim = Limits(ToleranceType.LOWER_ONLY, D("5"), None, D("5.000"), reference_width=D("0.100"))
    assert classify(D("4.999"), lim).result == Result.NOK
    assert classify(D("5.009"), lim).result == Result.MARGINAL  # g = 0.010
    assert classify(D("5.010"), lim).result == Result.OK
    assert classify(D("9.000"), lim).result == Result.OK  # no upper limit


def test_uncertainty_rule_marks_values_near_limit():
    lim = Limits(
        ToleranceType.BILATERAL,
        D("72"),
        D("72.030"),
        D("72.000"),
        guard_band_pct=D("0"),
        expanded_uncertainty=D("0.002"),
    )
    assert classify(D("72.029"), lim).result == Result.OK
    c = classify(D("72.029"), lim, uncertainty_rule=True)
    assert c.result == Result.MARGINAL
    assert c.reason == "within measurement uncertainty"
    assert classify(D("72.031"), lim, uncertainty_rule=True).result == Result.NOK


def test_part_result_is_worst():
    assert worst([Result.OK, Result.MARGINAL]) == Result.MARGINAL
    assert worst([Result.OK, Result.NOK, Result.MARGINAL]) == Result.NOK
    assert worst([]) == Result.OK


def test_limits_from_tolerances():
    assert limits_from_tolerances(D("72"), D("0.030"), D("0"), None, None) == (
        D("72.030"),
        D("72"),
    )
    assert limits_from_tolerances(D("72"), None, None, D("72.1"), D("71.9")) == (
        D("72.1"),
        D("71.9"),
    )


thousandths = st.integers(min_value=-200, max_value=230).map(lambda n: D(72) + D(n) / 1000)


@given(thousandths)
def test_property_outside_limits_is_never_conforming(x):
    if x > BORE.usl or x < BORE.lsl:
        assert classify(x, BORE).result == Result.NOK


@given(thousandths)
def test_property_inside_and_beyond_guard_band_is_ok(x):
    g = D("0.003")
    if BORE.lsl + g <= x <= BORE.usl - g:
        assert classify(x, BORE).result == Result.OK
