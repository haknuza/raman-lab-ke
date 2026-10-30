"""Transactional raw data, reference provenance, and exclusive run ownership."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import uuid

from . import __version__
from .devices import utc_now
from .model import ScanError, canonical, point_dict


@contextmanager
def run_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".run-lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ScanError(f"Run is locked: {lock}. If a process crashed, verify it and all devices are stopped before removing this file.") from exc
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"pid": os.getpid(), "created_utc": utc_now()}, stream)
        yield
    finally:
        lock.unlink()


class RunStore:
    def __init__(self, directory, plan=None, resume=False):
        self.directory = Path(directory)
        path = self.directory / "run.sqlite"
        exists = path.exists()
        if plan is None and not exists:
            raise ScanError(f"No run database: {path}")
        if plan is not None and exists and not resume:
            raise ScanError("Run already exists; choose another output directory or use --resume")
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        if not exists:
            with self.db:
                self.db.executescript('''
                    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE darks (id TEXT PRIMARY KEY, spectrum TEXT NOT NULL, created_utc TEXT NOT NULL);
                    CREATE TABLE points (
                        point_index INTEGER PRIMARY KEY, point TEXT NOT NULL,
                        spectrum TEXT NOT NULL, dark_id TEXT NOT NULL REFERENCES darks(id),
                        flags TEXT NOT NULL, stored_utc TEXT NOT NULL);
                    CREATE TABLE events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT NOT NULL,
                        kind TEXT NOT NULL, detail TEXT NOT NULL);
                ''')
                for key, value in {"schema_version": 1, "pipeline_version": __version__,
                                   "configuration": plan.snapshot, "config_sha256": plan.digest,
                                   "created_utc": utc_now(), "state": "created"}.items():
                    self.db.execute("INSERT INTO meta VALUES (?, ?)", (key, canonical(value)))
        try:
            if self.get("schema_version") != 1:
                raise ScanError("Unsupported run database schema")
            if plan is not None and self.get("config_sha256") != plan.digest:
                raise ScanError("Cannot resume with changed machine, sample, or acquisition configuration")
            if plan is None:
                # Reports/export use one consistent snapshot, even during a run.
                self.db.execute("BEGIN")
        except BaseException:
            self.db.close()
            raise

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, canonical(value)))

    def event(self, kind, detail=None):
        with self.db:
            self.db.execute("INSERT INTO events(at_utc,kind,detail) VALUES (?,?,?)", (utc_now(), kind, canonical(detail or {})))

    def completed(self):
        return {row[0] for row in self.db.execute("SELECT point_index FROM points")}

    def add_dark(self, spectrum):
        reference_id = str(uuid.uuid4())
        with self.db:
            self.db.execute("INSERT INTO darks VALUES (?,?,?)", (reference_id, canonical(spectrum), utc_now()))
        return reference_id

    def dark(self, reference_id):
        row = self.db.execute("SELECT spectrum FROM darks WHERE id=?", (reference_id,)).fetchone()
        if row is None:
            raise ScanError("Missing dark reference in run database")
        return json.loads(row[0])

    def save_point(self, point, spectrum, dark_id, flags):
        with self.db:
            # Plain INSERT deliberately forbids duplicate/overwrite acquisition.
            self.db.execute("INSERT INTO points VALUES (?,?,?,?,?,?)", (point.index, canonical(point_dict(point)),
                            canonical(spectrum), dark_id, canonical(flags), utc_now()))

    def save_uncommitted_capture(self, point, spectrum, dark_id, error):
        # Preserve a valid readout even when subsequent laser-off confirmation
        # fails. It must not become a completed/resumable scan point.
        directory = self.directory / "uncommitted-captures"
        directory.mkdir(exist_ok=True)
        path = directory / f"point-{point.index}-{uuid.uuid4()}.json"
        with path.open("x", encoding="utf-8") as stream:
            stream.write(canonical({"point": point_dict(point), "spectrum": spectrum,
                                    "dark_id": dark_id, "error": str(error), "committed": False}))
            stream.flush()
            os.fsync(stream.fileno())
        self.event("uncommitted_capture_saved", {"point": point.index, "path": str(path.name)})

    def rows(self):
        for row in self.db.execute("SELECT * FROM points ORDER BY point_index"):
            yield {**dict(row), "point": json.loads(row["point"]),
                   "spectrum": json.loads(row["spectrum"]), "flags": json.loads(row["flags"])}

    def close(self):
        self.db.close()
