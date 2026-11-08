"""Synthetic measurement model (Section 18.2). SYNTHETIC DEMO DATA ONLY.

Normal process noise per characteristic (sigma chosen so Cpk is about 1.3-1.8 when in control),
plus injectable effects: linear tool-wear drift, step shift, single outliers and rare suspect
values. Pure functions, deterministic for a given seed.
"""

import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal

from app.models.enums import CharKind, ToleranceType
from app.seed.masters import PARTS, CharSpec


@dataclass(frozen=True)
class Effect:
    """An injected special cause. `start` / `end` are part indices within the generated run."""

    kind: str  # "drift" | "shift" | "outlier" | "suspect"
    char_no: str
    machine: str | None = None
    start: int = 0
    end: int | None = None
    # drift: change per part (mm); shift: step size (mm); outlier: size in sigmas
    amount: float = 0.0

    def applies(self, index: int, machine: str, char_no: str) -> bool:
        if char_no != self.char_no or (self.machine and machine != self.machine):
            return False
        return index >= self.start and (self.end is None or index <= self.end)


@dataclass
class CharModel:
    spec: CharSpec
    mean: float
    sigma: float


@dataclass
class SyntheticProcess:
    """Generates successive parts for one part number."""

    part_no: str
    seed: int = 42
    effects: list[Effect] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.models = [self._model(c) for c in PARTS[self.part_no][1]]

    def _model(self, spec: CharSpec) -> CharModel:
        cpk = self.rng.uniform(1.3, 1.8)
        if spec.tolerance_type == ToleranceType.UPPER_ONLY:
            usl = float(spec.usl or 0)
            mean = 0.35 * usl
            return CharModel(spec, mean, (usl - mean) / (3 * cpk))
        lsl, usl = float(spec.lsl or 0), float(spec.usl or 0)
        return CharModel(spec, (lsl + usl) / 2, (usl - lsl) / (6 * cpk))

    def part(self, index: int, machine: str) -> dict[str, Decimal]:
        """Measured values for part number `index` made on `machine`."""
        values: dict[str, Decimal] = {}
        for m in self.models:
            x = self.rng.gauss(m.mean, m.sigma)
            for e in self.effects:
                if not e.applies(index, machine, m.spec.char_no):
                    continue
                if e.kind == "drift":
                    x += e.amount * (index - e.start)
                elif e.kind == "shift":
                    x += e.amount
                elif e.kind == "outlier" and index == e.start:
                    x = m.mean + e.amount * m.sigma
                elif e.kind == "suspect" and index == e.start:
                    # Probing / entry error: negative geometric value or a typo-sized dimension.
                    x = -0.001 if m.spec.kind == CharKind.GEOMETRIC else m.mean * 10
                    break
            else:
                if m.spec.tolerance_type == ToleranceType.UPPER_ONLY:
                    x = abs(x)  # geometric deviations are non-negative by nature
            values[m.spec.char_no] = quantize(x)
        return values


def quantize(x: float, decimals: int = 3) -> Decimal:
    return Decimal(repr(x)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)
