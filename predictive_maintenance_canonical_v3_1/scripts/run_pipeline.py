"""Build Source Data Producer assets and optionally regenerate ML fixtures.

The default flow stops at Canonical/source generation, source-side evaluation
fixtures, package validation, and reproducibility. The historical integrated
ML/prediction/Result Artifact pipeline runs only when explicitly requested for
migration/regression fixture regeneration.
"""

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
    parser = argparse.ArgumentParser(
        description="Run Canonical source generation + source/reference validation"
    )
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
    parser.add_argument(
        "--include-reference-model-fixtures",
        action="store_true",
        help=(
            "also regenerate the legacy ML/prediction/Result Artifact fixtures; "
            "this is migration/regression validation, not the product runtime pipeline"
        ),
    )
    parser.add_argument("--skip-model", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-reproducibility", action="store_true")
    args = parser.parse_args()

    scripts_dir = Path(__file__).resolve().parent
    root = scripts_dir.parent
    python = sys.executable
    include_reference_model_fixtures = args.include_reference_model_fixtures
    if args.skip_model:
        # Backward compatibility: source-only is now the default.
        include_reference_model_fixtures = False
    if not include_reference_model_fixtures:
        print(
            "[SOURCE-ONLY] Existing canonical/model_outputs are preserved but not "
            "validated against newly generated source data. Use "
            "--include-reference-model-fixtures for explicit fixture regeneration.",
            flush=True,
        )
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
    run(
        [
            python,
            str(scripts_dir / "validate_package.py"),
            "--root",
            str(root),
            "--source-only",
        ],
        scripts_dir,
    )
    if include_reference_model_fixtures:
        # Never allow reference artifacts from a previous dataset build to
        # masquerade as outputs of this explicit fixture-regeneration run.
        model_output_dir = root / "canonical" / "model_outputs"
        if model_output_dir.exists():
            shutil.rmtree(model_output_dir)
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
