"""Build the canonical package, optional agent cases, models, and validation."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run canonical dataset + agent evaluation pipeline")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--rate-profile",
        choices=["balanced_demo", "realistic_sparse", "training_dense"],
        default="balanced_demo",
    )
    parser.add_argument("--interventions", type=int, default=4)
    parser.add_argument("--duration-hours", type=int, default=24)
    parser.add_argument("--negative-cases", type=int, default=4)
    parser.add_argument("--skip-model", action="store_true")
    parser.add_argument("--skip-reproducibility", action="store_true")
    args = parser.parse_args()

    scripts_dir = Path(__file__).resolve().parent
    root = scripts_dir.parent
    python = sys.executable
    # Never allow model artifacts from a previous dataset build to masquerade
    # as outputs of the newly generated canonical dataset.
    model_output_dir = root / "canonical" / "model_outputs"
    if model_output_dir.exists():
        shutil.rmtree(model_output_dir)
    run(
        [
            python,
            str(scripts_dir / "generate_canonical_dataset.py"),
            "--root",
            str(root),
            "--days",
            str(args.days),
            "--seed",
            str(args.seed),
            "--rate-profile",
            args.rate_profile,
        ],
        scripts_dir,
    )
    run(
        [
            python,
            str(scripts_dir / "generate_agent_experiment.py"),
            "--root",
            str(root),
            "--seed",
            str(args.seed),
            "--interventions",
            str(args.interventions),
            "--duration-hours",
            str(args.duration_hours),
            "--negative-cases",
            str(args.negative_cases),
        ],
        scripts_dir,
    )
    run(
        [
            python,
            str(scripts_dir / "generate_agent_claim_examples.py"),
            "--root",
            str(root),
        ],
        scripts_dir,
    )
    run(
        [
            python,
            str(root / "agent" / "evaluate_agent_claims.py"),
            str(root / "agent" / "agent_claims.example.jsonl"),
            "--root",
            str(root),
            "--output",
            str(
                root
                / "canonical"
                / "validation"
                / "agent_claims_example_evaluation.json"
            ),
        ],
        scripts_dir,
    )
    run([python, str(scripts_dir / "validate_package.py"), "--root", str(root)], scripts_dir)
    if not args.skip_model:
        run(
            [
                python,
                str(root / "model" / "prediction_pipeline.py"),
                "--root",
                str(root),
                "--horizon-hours",
                "24",
            ],
            scripts_dir,
        )
        run([python, str(scripts_dir / "validate_package.py"), "--root", str(root)], scripts_dir)
    if not args.skip_reproducibility:
        run(
            [
                python,
                str(scripts_dir / "validate_reproducibility.py"),
                "--root",
                str(root),
                "--seed",
                str(args.seed),
                "--days",
                "5",
            ],
            scripts_dir,
        )


if __name__ == "__main__":
    main()
