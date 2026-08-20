"""Append-only persistence for generated SensorRecord values."""

from __future__ import annotations

import json
from pathlib import Path

from app.observation.models import SensorRecord


class SourceRecordWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8", newline="\n")
        self.count = 0

    def write(self, record: SensorRecord) -> None:
        self._handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        self.count += 1

    def flush(self) -> None:
        self._handle.flush()

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.flush()
            self._handle.close()

    def __enter__(self) -> "SourceRecordWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
