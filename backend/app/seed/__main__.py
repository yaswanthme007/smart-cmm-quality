"""`python -m app.seed [masters|history|storyline]`: seed SYNTHETIC demo data."""

import argparse
import logging

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging

logger = logging.getLogger("app.seed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic demo data")
    parser.add_argument(
        "what", nargs="?", default="masters", choices=["masters", "history", "storyline"]
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    configure_logging(get_settings().log_level)

    from app.seed.history import seed_history
    from app.seed.masters import seed_masters
    from app.seed.storyline import reset

    with get_sessionmaker().begin() as session:
        if args.what == "masters":
            logger.info("seeded demo masters: %s", seed_masters(session))
        elif args.what == "history":
            logger.info("seeded demo history: %s", seed_history(session, args.days, args.seed))
        else:
            logger.info("demo storyline reset: %s", reset(session, args.days, args.seed))


if __name__ == "__main__":
    main()
