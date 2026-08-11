"""Canonical source replay server with a controllable simulation clock.

This server never generates new sensor values. It replays the validated
canonical observations in timestamp order. When present, precomputed
``prediction_timeline.jsonl`` rows are V3.1 deterministic reference/regression
fixtures, not operational runtime inference. Product inference belongs to
ontology_dashboard/systems/backend/diagnosis. Evaluation truth and optional
experiment hidden truth are never exposed.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from flask import Flask, Response, abort, jsonify, request


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("simulation time must include an explicit timezone offset")
    return parsed


def load_csv_by_time(path: Path, time_field: str) -> dict[datetime, list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    indexed: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            indexed[parse_time(row[time_field])].append(row)
    return dict(indexed)


def load_jsonl_by_time(path: Path) -> dict[datetime, list[dict[str, object]]]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Run model/prediction_pipeline.py first."
        )
    indexed: dict[datetime, list[dict[str, object]]] = defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                indexed[parse_time(str(row["observed_at"]))].append(row)
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise ValueError(f"invalid timeline row at line {line_number}") from exc
    return dict(indexed)


class ReplayData:
    def __init__(self, root: Path) -> None:
        dataset_dir = root / "canonical" / "dataset"
        model_dir = root / "canonical" / "model_outputs"
        self.manifest = json.loads(
            (dataset_dir / "dataset_manifest.json").read_text(encoding="utf-8")
        )
        self.assets = self._read_all(dataset_dir / "asset_master.csv")
        self.relations = self._read_all(dataset_dir / "asset_relation.csv")
        self.compressors = load_csv_by_time(
            dataset_dir / "compressor_sensor_observation.csv", "observed_at"
        )
        self.cnc = load_csv_by_time(
            dataset_dir / "cnc_sensor_observation.csv", "observed_at"
        )
        self.production = load_csv_by_time(
            dataset_dir / "cnc_production_cycle.csv", "cycle_completed_at"
        )
        self.maintenance_started = load_csv_by_time(
            dataset_dir / "maintenance_event.csv", "started_at"
        )
        self.predictions = load_jsonl_by_time(
            model_dir / "prediction_timeline.jsonl"
        )

        sensor_times = sorted(set(self.compressors) & set(self.cnc))
        if not sensor_times:
            raise ValueError("canonical compressor/CNC observation clocks do not overlap")
        self.sensor_times = sensor_times
        self.prediction_times = sorted(self.predictions)
        self.start = sensor_times[0]
        self.end = sensor_times[-1]

    @staticmethod
    def _read_all(path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def sensor_index_at_or_before(self, value: datetime) -> int:
        return max(0, min(len(self.sensor_times) - 1, bisect.bisect_right(self.sensor_times, value) - 1))

    def prediction_time_at_or_before(self, value: datetime) -> datetime | None:
        index = bisect.bisect_right(self.prediction_times, value) - 1
        return self.prediction_times[index] if index >= 0 else None

    def snapshot(self, index: int) -> dict[str, object]:
        current = self.sensor_times[index]
        prediction_time = self.prediction_time_at_or_before(current)
        return {
            "simulation_time": current.isoformat(),
            "sensor_cadence_minutes": self.manifest["observation_interval_minutes"],
            "compressor_observations": self.compressors.get(current, []),
            "cnc_observations": self.cnc.get(current, []),
            "production_completions": self.production.get(current, []),
            "maintenance_started": self.maintenance_started.get(current, []),
            "prediction_time": prediction_time.isoformat() if prediction_time else None,
            "predictions": self.predictions.get(prediction_time, []) if prediction_time else [],
        }

    def history(
        self,
        asset_id: str,
        current_index: int,
        minutes: int,
    ) -> dict[str, object]:
        current = self.sensor_times[current_index]
        start = current - timedelta(minutes=minutes)
        first = bisect.bisect_left(self.sensor_times, start)
        rows: list[dict[str, str]] = []
        for timestamp in self.sensor_times[first : current_index + 1]:
            source = self.compressors.get(timestamp, []) + self.cnc.get(timestamp, [])
            rows.extend(row for row in source if row["asset_id"] == asset_id)
        return {
            "asset_id": asset_id,
            "window_start": start.isoformat(),
            "window_end": current.isoformat(),
            "minutes": minutes,
            "rows": rows,
        }


class ReplayEngine:
    def __init__(self, data: ReplayData, speed: float = 60.0, tick_seconds: float = 1.0) -> None:
        self.data = data
        self.speed = speed
        self.tick_seconds = tick_seconds
        self.index = 0
        self.cursor = data.start
        self.state = "stopped"
        self.sequence = 0
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.recent = deque(maxlen=120)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="canonical-replay", daemon=True)
        self._thread.start()

    def _publish(self) -> None:
        self.sequence += 1
        self.recent.append(
            {
                "sequence": self.sequence,
                "simulation_time": self.data.sensor_times[self.index].isoformat(),
                "state": self.state,
            }
        )
        self.condition.notify_all()

    def _run(self) -> None:
        last_real = time.monotonic()
        while not self._closed:
            time.sleep(self.tick_seconds)
            now = time.monotonic()
            elapsed = now - last_real
            last_real = now
            with self.condition:
                if self.state != "running":
                    continue
                self.cursor = min(
                    self.data.end,
                    self.cursor + timedelta(minutes=self.speed * elapsed),
                )
                next_index = self.data.sensor_index_at_or_before(self.cursor)
                if next_index == self.index and self.cursor < self.data.end:
                    continue
                self.index = next_index
                if self.index >= len(self.data.sensor_times) - 1:
                    self.state = "completed"
                self._publish()

    def status(self) -> dict[str, object]:
        with self.lock:
            return {
                "state": self.state,
                "sequence": self.sequence,
                "simulation_time": self.data.sensor_times[self.index].isoformat(),
                "speed_simulation_minutes_per_real_second": self.speed,
                "dataset_start": self.data.start.isoformat(),
                "dataset_end": self.data.end.isoformat(),
                "progress": round(self.index / max(1, len(self.data.sensor_times) - 1), 6),
                "sensor_cadence_minutes": self.data.manifest["observation_interval_minutes"],
            }

    def current_payload(self) -> dict[str, object]:
        with self.lock:
            return {"status": self.status(), "snapshot": self.data.snapshot(self.index)}

    def start(self, start_time: datetime | None = None, speed: float | None = None) -> dict[str, object]:
        with self.condition:
            if start_time is not None:
                self.index = self.data.sensor_index_at_or_before(start_time)
                self.cursor = self.data.sensor_times[self.index]
            elif self.state == "completed":
                self.index = 0
                self.cursor = self.data.start
            if speed is not None:
                self._set_speed(speed)
            self.state = "running"
            self._publish()
            return self.status()

    def pause(self) -> dict[str, object]:
        with self.condition:
            if self.state == "running":
                self.state = "paused"
                self._publish()
            return self.status()

    def resume(self) -> dict[str, object]:
        with self.condition:
            if self.state == "completed":
                raise ValueError("simulation completed; seek or reset before resume")
            self.state = "running"
            self._publish()
            return self.status()

    def reset(self) -> dict[str, object]:
        with self.condition:
            self.index = 0
            self.cursor = self.data.start
            self.state = "stopped"
            self._publish()
            return self.status()

    def seek(self, value: datetime) -> dict[str, object]:
        with self.condition:
            self.index = self.data.sensor_index_at_or_before(value)
            self.cursor = self.data.sensor_times[self.index]
            if self.state == "completed":
                self.state = "paused"
            self._publish()
            return self.status()

    def _set_speed(self, value: float) -> None:
        if not 0.1 <= value <= 10080:
            raise ValueError("speed must be between 0.1 and 10080 simulation minutes/second")
        self.speed = value

    def set_speed(self, value: float) -> dict[str, object]:
        with self.condition:
            self._set_speed(value)
            self._publish()
            return self.status()

    def wait_for_update(self, after_sequence: int, timeout: float = 15.0) -> int:
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > after_sequence, timeout=timeout)
            return self.sequence


def request_json() -> dict[str, object]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def create_app(root: Path, default_speed: float = 60.0) -> Flask:
    data = ReplayData(root)
    engine = ReplayEngine(data, speed=default_speed)
    app = Flask(__name__)

    @app.after_request
    def add_headers(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValueError)
    def handle_value_error(error: ValueError):
        return jsonify({"error": str(error)}), 400

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "server_type": "canonical_csv_replay",
                "generates_sensor_values": False,
                "truth_exposed": False,
                "timeline_available": bool(data.prediction_times),
            }
        )

    @app.get("/simulation/status")
    def simulation_status():
        return jsonify(engine.status())

    @app.get("/simulation/snapshot")
    def simulation_snapshot():
        return jsonify(engine.current_payload())

    @app.post("/simulation/start")
    def simulation_start():
        payload = request_json()
        start_time = parse_time(str(payload["time"])) if payload.get("time") else None
        speed = float(payload["speed"]) if payload.get("speed") is not None else None
        return jsonify(engine.start(start_time=start_time, speed=speed))

    @app.post("/simulation/pause")
    def simulation_pause():
        return jsonify(engine.pause())

    @app.post("/simulation/resume")
    def simulation_resume():
        return jsonify(engine.resume())

    @app.post("/simulation/reset")
    def simulation_reset():
        return jsonify(engine.reset())

    @app.post("/simulation/speed")
    def simulation_speed():
        payload = request_json()
        raw = request.args.get("x", payload.get("x"))
        if raw is None:
            raise ValueError("speed is required as ?x=60 or JSON {\"x\": 60}")
        return jsonify(engine.set_speed(float(raw)))

    @app.post("/simulation/seek")
    def simulation_seek():
        payload = request_json()
        raw = request.args.get("time", payload.get("time"))
        if not raw:
            raise ValueError("time is required as an ISO-8601 timestamp with timezone")
        return jsonify(engine.seek(parse_time(str(raw))))

    @app.get("/simulation/history")
    def simulation_history():
        asset_id = request.args.get("asset_id", "")
        if not asset_id:
            raise ValueError("asset_id is required")
        try:
            minutes = int(request.args.get("minutes", "360"))
        except ValueError as exc:
            raise ValueError("minutes must be an integer") from exc
        if not 10 <= minutes <= 10080:
            raise ValueError("minutes must be between 10 and 10080")
        known_assets = {row["asset_id"] for row in data.assets}
        if asset_id not in known_assets:
            abort(404, description=f"unknown asset_id: {asset_id}")
        with engine.lock:
            return jsonify(data.history(asset_id, engine.index, minutes))

    @app.get("/simulation/events")
    def simulation_events():
        def stream() -> Iterator[str]:
            sequence = -1
            while True:
                current = engine.wait_for_update(sequence)
                if current == sequence:
                    yield ": keep-alive\n\n"
                    continue
                sequence = current
                payload = json.dumps(engine.current_payload(), ensure_ascii=False)
                yield f"id: {sequence}\nevent: simulation\ndata: {payload}\n\n"

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/assets")
    def assets():
        return jsonify(data.assets)

    @app.get("/relations")
    def relations():
        return jsonify(data.relations)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay validated canonical CSV data")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--speed",
        type=float,
        default=60.0,
        help="simulation minutes advanced per real second",
    )
    args = parser.parse_args()
    create_app(Path(args.root), default_speed=args.speed).run(
        host=args.host,
        port=args.port,
        debug=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
