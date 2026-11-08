"""Synthetic CMM report generator (Section 18.2). SYNTHETIC DEMO DATA ONLY.

Examples (from the repo root):
    make gen
    cd backend && uv run python ../tools/generator/generate.py --style all --count 5
    cd backend && uv run python ../tools/generator/generate.py --style calypso --part DC-101 \
        --machine VMC-02 --serial-start 457 --count 1 --set C-03=72.034 --flat \
        --out ../data/inbox/CMM-01
    cd backend && uv run python ../tools/generator/generate.py --history 30d   # into the DB
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from writers import write_aqdef, write_calypso, write_csv  # noqa: E402

from app.seed.masters import PARTS  # noqa: E402
from app.seed.synthetic import Effect, SyntheticProcess  # noqa: E402

STYLES = {
    "csv": ("generic_csv", write_csv),
    "pcdmis": ("pcdmis_csv", write_csv),
    "calypso": ("calypso", write_calypso),
    "aqdef": ("aqdef", write_aqdef),
}


def parse_effect(text: str, kind: str) -> Effect:
    """`C-03:0.0008` or `C-03@VMC-02:0.0008[:start]`."""
    head, _, rest = text.partition(":")
    char_no, _, machine = head.partition("@")
    amount, _, start = rest.partition(":")
    return Effect(kind, char_no, machine or None, int(start or 0), None, float(amount))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--style", choices=[*STYLES, "all"], default="all")
    p.add_argument("--part", choices=list(PARTS), default=None, help="default: all parts")
    p.add_argument("--machine", default="VMC-02")
    p.add_argument("--count", type=int, default=3, help="parts per part number")
    p.add_argument("--serial-start", type=int, default=1)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, default=ROOT / "samples")
    p.add_argument("--flat", action="store_true", help="write straight into --out (no subfolder)")
    p.add_argument("--decimal-comma", action="store_true", help="German-locale CSV (; and ,)")
    p.add_argument("--drift", action="append", default=[], metavar="CHAR[@MACHINE]:MM_PER_PART")
    p.add_argument("--shift", action="append", default=[], metavar="CHAR[@MACHINE]:MM[:START]")
    p.add_argument("--set", action="append", default=[], metavar="CHAR=VALUE", help="force value")
    p.add_argument("--history", metavar="DAYS", help="insert e.g. 30d of history into the DB")
    args = p.parse_args(argv)

    if args.history:
        from app.seed.history import main as history_main

        return history_main(int(args.history.rstrip("d")), seed=args.seed)

    effects = [parse_effect(t, "drift") for t in args.drift]
    effects += [parse_effect(t, "shift") for t in args.shift]
    forced = {k: Decimal(v) for k, v in (s.split("=", 1) for s in args.set)}
    styles = list(STYLES) if args.style == "all" else [args.style]
    parts = [args.part] if args.part else list(PARTS)
    now = datetime.now(UTC).replace(microsecond=0)

    written = []
    for part_no in parts:
        proc = SyntheticProcess(part_no, seed=args.seed, effects=effects)
        for i in range(args.count):
            serial = f"{args.serial_start + i:04d}"
            values = proc.part(i, args.machine) | forced
            measured_at = now - timedelta(minutes=5 * (args.count - i))
            for style in styles:
                sub, writer = STYLES[style]
                out = args.out if args.flat else args.out / sub
                out.mkdir(parents=True, exist_ok=True)
                if writer is write_csv:
                    path = write_csv(out, part_no, serial, values, measured_at, args.decimal_comma)
                else:
                    path = writer(out, part_no, serial, values, measured_at, args.machine)
                written.append(path)
    for path in written:
        print(path)
    print(f"wrote {len(written)} synthetic report file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
