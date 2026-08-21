"""Check deterministic generation for canonical and public experiment assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path

from generate_agent_experiment import generate as generate_experiment
from generate_canonical_dataset import generate as generate_dataset


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_run(root: Path, seed: int, days: int, scope: str) -> None:
    generate_dataset(
        root=root,
        start_at=datetime.fromisoformat("2026-08-01T00:00:00+09:00"),
        days=days,
        interval_minutes=10,
        product_cycle_minutes=20,
        seed=seed,
        rate_profile="balanced_demo",
    )
    if scope == "full":
        generate_experiment(root=root, seed=seed, interventions=1, duration_hours=12)


def checksums(root: Path, scope: str) -> dict[str, str]:
    included: dict[str, str] = {}
    relative_roots = [
        "canonical/dataset",
        "canonical/evaluation_truth",
    ]
    if scope == "full":
        relative_roots.append("experiments")
    for relative_root in relative_roots:
        base = root / relative_root
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            # Manifests contain created_at or hashes of manifests containing it.
            if path.name in {"dataset_manifest.json", "experiment_manifest.json"}:
                continue
            included[path.relative_to(root).as_posix()] = sha256(path)
    return included


def validate(root: Path, seed: int, days: int, scope: str) -> dict[str, object]:
    if days < 1:
        raise ValueError("--days must be at least 1")
    if scope == "full" and days < 5:
        raise ValueError(
            "--days must be at least 5 when --scope full because optional "
            "experiment cases require complete pre/during/post windows"
        )
    with tempfile.TemporaryDirectory(prefix="canonical-agent-repro-") as temporary:
        temporary_root = Path(temporary)
        same_a = temporary_root / "same-a"
        same_b = temporary_root / "same-b"
        different = temporary_root / "different"
        generate_run(same_a, seed, days, scope)
        generate_run(same_b, seed, days, scope)
        generate_run(different, seed + 1, days, scope)
        first = checksums(same_a, scope)
        second = checksums(same_b, scope)
        third = checksums(different, scope)
        same_seed_identical = first == second
        changed = sorted(
            name for name in set(first) | set(third) if first.get(name) != third.get(name)
        )
        result = {
            "valid": same_seed_identical and bool(changed),
            "scope": scope,
            "days": days,
            "seed": seed,
            "same_seed_outputs_identical": same_seed_identical,
            "different_seed_changes_outputs": bool(changed),
            "different_seed_changed_file_count": len(changed),
            "different_seed_changed_files": changed,
            "checked_file_count": len(first),
        }
    output = root / "canonical" / "validation" / "reproducibility_validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate deterministic package generation")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--scope", choices=["canonical", "full"], default="full")
    args = parser.parse_args()
    print(
        json.dumps(
            validate(Path(args.root), args.seed, args.days, args.scope),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

