"""Watched-folder ingestion (Section 8.4).

- One inbox per CMM: data/inbox/<CMM-CODE>/; outputs data/processed/<CMM>/<YYYY-MM-DD>/ and
  data/failed/<CMM>/ (+ <name>.error.txt).
- File-stability check: CMM software writes progressively, so a file is ingested only when its
  size is unchanged across 2 checks 1 s apart and it can be opened for reading.
- watchdog events plus a 5 s polling fallback (network shares do not always emit events).
- CALYPSO-style `<name>_chr.txt` is ingested together with its `<name>_hdr.txt` header file.
"""

import asyncio
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.db import get_sessionmaker
from app.models.enums import ReportSource, ReportStatus
from app.services import audit
from app.services.ingestion.pipeline import (
    ALLOWED_EXTENSIONS,
    DuplicateReport,
    IngestRejected,
    IngestRequest,
    ingest_file,
)

logger = logging.getLogger("app.worker.folder")

STABLE_CHECK_S = 1.0
POLL_S = 5.0
COMPANION_SUFFIX = "_hdr.txt"


@dataclass
class Pending:
    first_seen: datetime
    size: int = -1
    stable_count: int = 0


def is_candidate(path: Path) -> bool:
    name = path.name.lower()
    if (
        name.startswith(".")
        or name.startswith("~")
        or name.endswith((".tmp", ".part", ".error.txt"))
    ):
        return False
    if name.endswith(COMPANION_SUFFIX):
        return False
    return path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS


def companion_of(path: Path) -> Path | None:
    if path.name.lower().endswith("_chr.txt"):
        hdr = path.with_name(path.name[: -len("_chr.txt")] + COMPANION_SUFFIX)
        return hdr if hdr.exists() else None
    return None


class FolderWatcher:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.inbox = self.data_dir / "inbox"
        self.pending: dict[Path, Pending] = {}
        self.lock = threading.Lock()
        self._observer = None

    # ------------------------------------------------------------ discovery

    def note(self, path: Path) -> None:
        if is_candidate(path):
            with self.lock:
                self.pending.setdefault(path, Pending(first_seen=datetime.now(UTC)))

    def scan(self) -> None:
        if not self.inbox.exists():
            return
        for cmm_dir in self.inbox.iterdir():
            if cmm_dir.is_dir():
                for path in cmm_dir.iterdir():
                    self.note(path)

    def start_observer(self) -> None:
        try:
            from watchdog.events import FileSystemEvent, FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:  # pragma: no cover
            return

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event: FileSystemEvent) -> None:
                watcher.note(Path(str(event.src_path)))

            def on_moved(self, event: FileSystemEvent) -> None:
                watcher.note(Path(str(event.dest_path)))

            def on_modified(self, event: FileSystemEvent) -> None:
                watcher.note(Path(str(event.src_path)))

        self.inbox.mkdir(parents=True, exist_ok=True)
        observer = Observer()
        observer.schedule(Handler(), str(self.inbox), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()

    # ------------------------------------------------------------ stability + ingest

    def stable_files(self) -> list[tuple[Path, datetime]]:
        """Advance stability counters; return files stable across 2 checks and readable."""
        ready = []
        with self.lock:
            for path, p in list(self.pending.items()):
                if not path.exists():
                    del self.pending[path]
                    continue
                size = path.stat().st_size
                if size == p.size and size > 0:
                    p.stable_count += 1
                else:
                    p.size, p.stable_count = size, 0
                if p.stable_count >= 1:  # unchanged across 2 consecutive checks
                    try:
                        with path.open("rb"):
                            pass
                    except OSError:
                        continue
                    ready.append((path, p.first_seen))
                    del self.pending[path]
        return ready

    def _move(self, path: Path, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / path.name
        if dest.exists():
            dest = target_dir / f"{path.stem}_{int(time.time())}{path.suffix}"
        shutil.move(str(path), dest)
        return dest

    def ingest_one(self, path: Path, received_at: datetime) -> ReportStatus | str:
        cmm_code = path.parent.name
        hdr = companion_of(path)
        companions = {hdr.name: hdr.read_bytes()} if hdr else {}
        data = path.read_bytes()
        req = IngestRequest(
            source=ReportSource.WATCH_FOLDER,
            received_at=received_at,
            actor=audit.Actor(user_id=None, role="SYSTEM"),
            filename=path.name,
            cmm_code=cmm_code,
            file_mtime=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            companions=companions,
        )
        error = None
        outcome: ReportStatus | str
        with get_sessionmaker()() as session:
            try:
                result = ingest_file(session, data, req)
                session.commit()
                outcome = result.report.status
                if result.report.status == ReportStatus.FAILED:
                    error = "\n".join(result.errors)
                logger.info("ingested %s as %s (%s)", path.name, result.report.report_no, outcome)
            except DuplicateReport as exc:
                session.rollback()
                outcome, error = "DUPLICATE", f"duplicate of report {exc.report.report_no}"
            except IngestRejected as exc:
                session.rollback()
                outcome, error = "REJECTED", exc.message
            except Exception as exc:
                session.rollback()
                logger.exception("ingest of %s crashed", path.name)
                outcome, error = "ERROR", f"internal error: {exc}"

        day = datetime.now(UTC).strftime("%Y-%m-%d")
        if error is None:
            target = self.data_dir / "processed" / cmm_code / day
        else:
            target = self.data_dir / "failed" / cmm_code
        moved = self._move(path, target)
        if hdr is not None and hdr.exists():
            self._move(hdr, target)
        if error is not None:
            moved.with_name(moved.name + ".error.txt").write_text(error + "\n", encoding="utf-8")
        return outcome

    def tick(self) -> int:
        count = 0
        for path, first_seen in self.stable_files():
            self.ingest_one(path, first_seen)
            count += 1
        return count

    async def run(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.start_observer()
        last_scan = 0.0
        while True:
            try:
                if time.monotonic() - last_scan >= POLL_S:
                    await asyncio.to_thread(self.scan)
                    last_scan = time.monotonic()
                await asyncio.to_thread(self.tick)
            except Exception:
                logger.exception("folder watcher tick failed")
            await asyncio.sleep(STABLE_CHECK_S)
