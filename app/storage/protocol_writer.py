"""Append-only OPC UA provenance, quarantine and failure records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProtocolRecordWriter:
    def __init__(self, protocol_dir: Path) -> None:
        protocol_dir.mkdir(parents=True, exist_ok=True)
        self.provenance_path = protocol_dir / "provenance.jsonl"
        self.error_path = protocol_dir / "errors.jsonl"
        self.quarantine_path = protocol_dir / "quarantine.jsonl"
        self._provenance = self.provenance_path.open("a", encoding="utf-8", newline="\n")
        self._errors = self.error_path.open("a", encoding="utf-8", newline="\n")
        self._quarantine = self.quarantine_path.open("a", encoding="utf-8", newline="\n")
        self.datavalue_count = 0
        self.error_count = 0
        self.quarantine_count = 0

    def write_provenance(self, payload: dict[str, Any]) -> None:
        self._provenance.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.datavalue_count += 1

    def write_error(self, payload: dict[str, Any]) -> None:
        self._errors.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.error_count += 1

    def write_quarantine(self, payload: dict[str, Any]) -> None:
        self._quarantine.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.quarantine_count += 1

    def flush(self) -> None:
        self._provenance.flush()
        self._errors.flush()
        self._quarantine.flush()

    def close(self) -> None:
        for handle in (self._provenance, self._errors, self._quarantine):
            if not handle.closed:
                handle.flush()
                handle.close()

    def __enter__(self) -> "ProtocolRecordWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
