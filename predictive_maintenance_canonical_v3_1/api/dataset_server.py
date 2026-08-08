"""Read-only API for canonical data, model outputs, and public experiment cases."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from flask import Flask, abort, jsonify, request


def read_csv_page(path: Path, offset: int, limit: int) -> dict[str, object]:
    if not path.exists():
        abort(404, description=f"file not found: {path.name}")
    rows: list[dict[str, str]] = []
    total = 0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            total += 1
            if index < offset or len(rows) >= limit:
                continue
            rows.append(row)
        fields = list(reader.fieldnames or [])
    return {"file": path.name, "offset": offset, "limit": limit, "total": total, "fields": fields, "rows": rows}


def safe_page_args() -> tuple[int, int]:
    try:
        offset = max(0, int(request.args.get("offset", "0")))
        limit = min(1000, max(1, int(request.args.get("limit", "100"))))
    except ValueError:
        abort(400, description="offset and limit must be integers")
    return offset, limit


def create_app(root: Path) -> Flask:
    app = Flask(__name__)
    dataset_dir = root / "canonical" / "dataset"
    model_dir = root / "canonical" / "model_outputs"
    experiment_root = root / "experiments" / "connected_air_supply"

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "canonical_dataset": (dataset_dir / "dataset_manifest.json").exists(),
                "model_outputs": (model_dir / "model_contract.json").exists(),
                "result_artifacts": (model_dir / "result_artifact.jsonl").exists(),
                "agent_experiments": (experiment_root / "public_case_index.csv").exists(),
            }
        )

    @app.get("/manifest")
    def manifest():
        path = dataset_dir / "dataset_manifest.json"
        if not path.exists():
            abort(404)
        return jsonify(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/assets")
    def assets():
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(dataset_dir / "asset_master.csv", offset, limit))

    @app.get("/relations")
    def relations():
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(dataset_dir / "asset_relation.csv", offset, limit))

    @app.get("/observations/compressors")
    def compressor_observations():
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(dataset_dir / "compressor_sensor_observation.csv", offset, limit))

    @app.get("/observations/cnc")
    def cnc_observations():
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(dataset_dir / "cnc_sensor_observation.csv", offset, limit))

    @app.get("/production")
    def production():
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(dataset_dir / "cnc_production_cycle.csv", offset, limit))

    @app.get("/maintenance")
    def maintenance():
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(dataset_dir / "maintenance_event.csv", offset, limit))

    @app.get("/predictions")
    def predictions():
        path = model_dir / "prediction_snapshot.jsonl"
        if not path.exists():
            abort(404)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return jsonify(rows)

    @app.get("/prediction-factors")
    def prediction_factors():
        path = model_dir / "prediction_factor.jsonl"
        if not path.exists():
            abort(404)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return jsonify(rows)

    @app.get("/result-artifacts")
    def result_artifacts():
        path = model_dir / "result_artifact.jsonl"
        if not path.exists():
            abort(404)
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return jsonify(rows)

    @app.get("/prediction-timeline")
    def prediction_timeline():
        path = model_dir / "prediction_timeline.jsonl"
        if not path.exists():
            abort(404)
        try:
            offset, limit = safe_page_args()
        except ValueError:
            raise
        rows: list[dict[str, object]] = []
        total = 0
        with path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if not line.strip():
                    continue
                total += 1
                if index < offset or len(rows) >= limit:
                    continue
                rows.append(json.loads(line))
        return jsonify(
            {
                "file": path.name,
                "offset": offset,
                "limit": limit,
                "total": total,
                "rows": rows,
            }
        )

    @app.get("/experiments")
    def experiments():
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(experiment_root / "public_case_index.csv", offset, limit))

    @app.get("/experiments/<case_id>")
    def experiment_case(case_id: str):
        case_dir = experiment_root / "public_cases" / case_id
        case_path = case_dir / "case.json"
        if not case_path.exists():
            abort(404)
        return jsonify(json.loads(case_path.read_text(encoding="utf-8")))

    @app.get("/experiments/<case_id>/<table_name>")
    def experiment_table(case_id: str, table_name: str):
        allowed = {
            "assets": "asset_master.csv",
            "relations": "asset_relation.csv",
            "compressors": "compressor_sensor_observation.csv",
            "cnc": "cnc_sensor_observation.csv",
        }
        filename = allowed.get(table_name)
        if filename is None:
            abort(404)
        offset, limit = safe_page_args()
        return jsonify(read_csv_page(experiment_root / "public_cases" / case_id / filename, offset, limit))

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve canonical source and public experiment assets")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    create_app(Path(args.root)).run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

