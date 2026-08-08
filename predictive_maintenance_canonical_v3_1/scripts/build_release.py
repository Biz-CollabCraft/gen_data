"""Build a cross-platform ZIP release with an English root directory."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


EXCLUDED_PARTS = {
    "__MACOSX",
    "__pycache__",
    ".venv",
    ".audit-venv",
    ".git",
    "dist",
}
EXCLUDED_PATTERNS = {".DS_Store", "._*", "*.pyc", "*.pyo"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded(relative: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return True
    return any(fnmatch.fnmatch(relative.name, pattern) for pattern in EXCLUDED_PATTERNS)


def validate_package(root: Path) -> None:
    validator = root / "scripts" / "validate_package.py"
    subprocess.run(
        [sys.executable, str(validator), "--root", str(root)],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    summary = json.loads(
        (root / "canonical" / "validation" / "package_validation.json").read_text(
            encoding="utf-8"
        )
    )
    if summary.get("valid") is not True or summary.get("model_contract") != "pass":
        raise RuntimeError("release requires a fully validated canonical package and model timeline")


def build(root: Path, output_dir: Path) -> tuple[Path, Path]:
    if not root.name.isascii():
        raise ValueError("release root directory must use an ASCII-only name")
    validate_package(root)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{root.name}.zip"
    checksum_path = output_dir / f"{root.name}.zip.sha256"
    archive.unlink(missing_ok=True)
    checksum_path.unlink(missing_ok=True)

    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        strict_timestamps=False,
    ) as bundle:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if excluded(relative):
                continue
            bundle.write(path, Path(root.name) / relative)

    with zipfile.ZipFile(archive) as bundle:
        bad_member = bundle.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP integrity failure: {bad_member}")
        names = bundle.namelist()
        if not names or any(not name.startswith(f"{root.name}/") for name in names):
            raise RuntimeError("ZIP root layout is invalid")
        if any(
            excluded(Path(name).relative_to(root.name))
            for name in names
            if name != f"{root.name}/"
        ):
            raise RuntimeError("excluded platform artifact leaked into ZIP")

    # Validate after a real extraction, catching encoding and relative-path issues.
    with tempfile.TemporaryDirectory(prefix="predictive-maintenance-release-") as temporary:
        temporary_root = Path(temporary)
        shutil.unpack_archive(str(archive), str(temporary_root))
        extracted = temporary_root / root.name
        if not extracted.exists():
            raise RuntimeError("extracted release root is missing")
        validate_package(extracted)

    checksum = sha256(archive)
    checksum_path.write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    return archive, checksum_path


def main() -> None:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build validated cross-platform ZIP release")
    parser.add_argument("--root", default=str(default_root))
    parser.add_argument("--output-dir", default=str(default_root / "dist"))
    args = parser.parse_args()
    archive, checksum = build(Path(args.root).resolve(), Path(args.output_dir).resolve())
    print(
        json.dumps(
            {
                "archive": str(archive),
                "sha256_file": str(checksum),
                "archive_sha256": sha256(archive),
                "size_bytes": archive.stat().st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
