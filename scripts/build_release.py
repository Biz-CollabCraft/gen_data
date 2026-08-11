"""Build the complete Canonical V3.1 source/reference fixture ZIP release.

This historical package release intentionally includes validated ML/prediction/
Result Artifact regression fixtures. Requiring those fixtures for this ZIP does
not make gen_data their operational product owner.
"""

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


DEFAULT_PACKAGE_NAME = "predictive_maintenance_canonical_v3_1"

EXCLUDED_PARTS = {
    "__MACOSX",
    "__pycache__",
    ".venv",
    ".audit-venv",
    ".git",
    "dist",
}
EXCLUDED_PATTERNS = {".DS_Store", "._*", "*.pyc", "*.pyo"}

RELEASE_DIRECTORIES = (
    "agent",
    "api",
    "canonical",
    "dashboard",
    "experiments",
    "model",
    "scripts",
    "tests",
)

RELEASE_TOP_LEVEL_FILES = (
    "ARCHITECTURE_DECISION.md",
    "FINAL_AUDIT_REPORT.md",
    "OWNERSHIP_AND_MIGRATION.md",
    "RESULT_ARTIFACT_SCHEMA.md",
    "SCHEMA.md",
    "V3_1_CHANGELOG.md",
    "V3_1_IMPLEMENTATION_REPORT.md",
    "V3_1_RELEASE_VERIFICATION.md",
    "requirements-lock.txt",
    "requirements-optional.txt",
    "requirements.txt",
    "result_artifact_sample.json",
)


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
        raise RuntimeError(
            "complete reference release requires validated Canonical source and "
            "model/prediction/result fixtures"
        )


def release_files(root: Path) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []

    canonical_readme = root / "CANONICAL_V3_1.md"
    if not canonical_readme.is_file():
        raise FileNotFoundError("CANONICAL_V3_1.md is required for the release package")
    files.append((canonical_readme, Path("README.md")))

    for name in RELEASE_TOP_LEVEL_FILES:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"required release file is missing: {name}")
        files.append((path, Path(name)))

    for directory in RELEASE_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            raise FileNotFoundError(f"required release directory is missing: {directory}")
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if excluded(relative):
                continue
            files.append((path, relative))

    return files


def build(
    root: Path,
    output_dir: Path,
    *,
    package_name: str = DEFAULT_PACKAGE_NAME,
) -> tuple[Path, Path]:
    if not package_name or not package_name.isascii():
        raise ValueError("release package name must be a non-empty ASCII string")
    if "/" in package_name or "\\" in package_name:
        raise ValueError("release package name must not contain path separators")
    validate_package(root)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{package_name}.zip"
    checksum_path = output_dir / f"{package_name}.zip.sha256"
    archive.unlink(missing_ok=True)
    checksum_path.unlink(missing_ok=True)

    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        strict_timestamps=False,
    ) as bundle:
        for path, relative in release_files(root):
            bundle.write(path, Path(package_name) / relative)

    with zipfile.ZipFile(archive) as bundle:
        bad_member = bundle.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP integrity failure: {bad_member}")
        names = bundle.namelist()
        if not names or any(not name.startswith(f"{package_name}/") for name in names):
            raise RuntimeError("ZIP root layout is invalid")
        if any(
            excluded(Path(name).relative_to(package_name))
            for name in names
            if name != f"{package_name}/"
        ):
            raise RuntimeError("excluded platform artifact leaked into ZIP")

    # Validate after a real extraction, catching encoding and relative-path issues.
    with tempfile.TemporaryDirectory(prefix="predictive-maintenance-release-") as temporary:
        temporary_root = Path(temporary)
        shutil.unpack_archive(str(archive), str(temporary_root))
        extracted = temporary_root / package_name
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
    parser.add_argument("--package-name", default=DEFAULT_PACKAGE_NAME)
    args = parser.parse_args()
    archive, checksum = build(
        Path(args.root).resolve(),
        Path(args.output_dir).resolve(),
        package_name=args.package_name,
    )
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
