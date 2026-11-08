"""Golden SPC fixture (Section 12.4) and one triggering / non-triggering fixture per Nelson rule."""

import pytest

from app.services.spc import capability, imr_limits, rules_anywhere, rules_at

GOLDEN = [10.0, 10.2, 9.9, 10.1, 10.0, 10.3, 9.8, 10.1, 10.0, 10.2]
TOL = 1e-6


def test_golden_imr_limits():
    lim = imr_limits(GOLDEN)
    assert lim.center == pytest.approx(10.06, abs=TOL)
    assert lim.mr_bar == pytest.approx(2.2 / 9, abs=TOL)
    assert lim.mr_bar == pytest.approx(0.244444, abs=TOL)
    assert lim.sigma == pytest.approx(0.216706, abs=TOL)
    assert lim.ucl == pytest.approx(10.710222, abs=TOL)
    assert lim.lcl == pytest.approx(9.409778, abs=TOL)
    assert lim.ucl_mr == pytest.approx(0.798600, abs=TOL)


C, S = 10.0, 0.1  # centre and sigma for the rule fixtures
ALL = ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8"]


def triggered(values, rule):
    return rule in [r for r, _ in rules_at(values, C, S, [rule])]


@pytest.mark.parametrize(
    ("rule", "hit", "miss"),
    [
        ("N1", [10.0, 10.31], [10.0, 10.29]),
        ("N2", [10.01] * 9, [10.01] * 8 + [9.99]),
        (
            "N3",
            [10.00, 10.01, 10.02, 10.03, 10.04, 10.05],
            [10.00, 10.01, 10.02, 10.03, 10.04, 10.04],
        ),
        (
            "N4",
            [10.0 + (0.01 if i % 2 else -0.01) for i in range(14)],
            [10.0 + (0.01 if i % 2 else -0.01) for i in range(13)] + [9.98],
        ),
        ("N5", [10.21, 10.0, 10.22], [10.21, 10.0, 9.78]),
        ("N6", [10.11, 10.12, 10.0, 10.13, 10.14], [10.11, 10.12, 10.0, 10.0, 10.14]),
        ("N7", [10.0 + (0.05 if i % 3 else -0.05) for i in range(15)], [10.0] * 14 + [10.15]),
        ("N8", [10.15, 9.85] * 4, [10.15, 9.85] * 3 + [10.15, 10.05]),
    ],
)
def test_nelson_rule_fixtures(rule, hit, miss):
    assert triggered(hit, rule)
    assert not triggered(miss, rule)


def test_rules_anywhere_marks_points():
    values = [10.0, 10.0, 10.5, 10.0]
    assert ("N1", 2) in rules_anywhere(values, C, S, ["N1"])


def test_capability_gate_insufficient_data():
    cap = capability([10.0] * 29, 10.5, 9.5, 0.1, active_signals=0)
    assert not cap.valid
    assert "Insufficient data" in cap.message


def test_capability_gate_unstable_process():
    cap = capability([10.0, 10.1] * 20, 10.5, 9.5, 0.1, active_signals=1)
    assert not cap.valid
    assert cap.message == "Process not stable, capability not valid"


def test_capability_values():
    values = [10.0, 10.1] * 20
    cap = capability(values, 10.6, 9.5, 0.1, active_signals=0)
    assert cap.valid
    assert cap.cp == pytest.approx(1.1 / 0.6)
    assert cap.cpk == pytest.approx((10.6 - 10.05) / 0.3)  # both sides 0.55 from the mean
    assert cap.pp is not None and cap.ppk is not None


def test_capability_one_sided():
    cap = capability([0.010, 0.012] * 20, 0.050, None, 0.002, active_signals=0)
    assert cap.valid
    assert cap.cp is None
    assert cap.cpk == pytest.approx((0.050 - 0.011) / 0.006)
