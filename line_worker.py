# ──────────────────────────────────────────────
# 단일 라인 1개 틱 주기 처리 워커 모듈
# ──────────────────────────────────────────────

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from protocol.raw_envelope import write_envelope

PROTOCOL_ADAPTERS: dict = {}  # daemon.py에서 기동 시 등록 (protocol_name -> AdapterClass)


# ──────────────────────────────────────────────
# 라인 워커 클래스
# ──────────────────────────────────────────────

class LineWorker:
    """단일 라인의 1개 틱 물리값 계산 및 RAW/Processed 아펜드 아키텍처 워커."""

    def __init__(
        self,
        site_id: str,
        cell_id: str,
        line_assets: list[dict],
        runtimes: dict,
        episodes_by_asset: dict,
        config,
        default_adapter,
        observation_allowed=None,
    ):
        self.site_id = str(site_id)
        self.cell_id = str(cell_id)
        self.assets = line_assets
        self.runtimes = runtimes
        self.episodes_by_asset = episodes_by_asset
        self.config = config
        self.observation_allowed = observation_allowed

        self.line_dir = Path(config.GEN_DATA_OUTPUT_DIR) / "raw" / f"fac{self.site_id}" / f"line{self.cell_id}"
        self.line_dir.mkdir(parents=True, exist_ok=True)

        self.adapter = self._resolve_adapter(default_adapter)
        self.unit_map = self._load_or_create_unit_map()

    def _resolve_adapter(self, default_adapter):
        """라인 폴더의 override 파일이 있을 경우 적용, 없으면 전역 기본 어댑터 반환."""
        override_path = self.line_dir / "line_protocol_map.json"
        if not override_path.exists():
            return default_adapter
        try:
            protocol_name = json.loads(override_path.read_text(encoding="utf-8"))["protocol"]
            return PROTOCOL_ADAPTERS[protocol_name]()
        except Exception:
            return default_adapter

    def _load_or_create_unit_map(self) -> dict:
        """라인 내 asset_id ↔ unit_id 매핑 JSON 파일 로드 또는 생성."""
        unit_path = self.line_dir / "line_unit_map.json"
        if unit_path.exists():
            return json.loads(unit_path.read_text(encoding="utf-8")).get("unit_map", {})
        unit_map = {str(i + 1): a["asset_id"] for i, a in enumerate(self.assets)}
        unit_path.write_text(json.dumps({"unit_map": unit_map}, ensure_ascii=False, indent=2), encoding="utf-8")
        return unit_map

    def _current_raw_path(self, observed_at: datetime) -> Path:
        """관측 일자별 RAW 파일 저장 경로 산출."""
        day_dir = self.line_dir / observed_at.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / f"{observed_at.strftime('%H%M%S')}.raw"

    def run_one_cycle(self, observed_at: datetime) -> None:
        """지정된 관측 시각(observed_at) 1개 틱에 대한 전 자산 물리 계산 및 아펜드 기입."""
        raw_values = {
            a["asset_id"]: self._compute_physics_value(a, observed_at)
            for a in self.assets
            if self.observation_allowed is None
            or self.observation_allowed(a["asset_id"], observed_at)
        }
        frame = self.adapter.encode_response(self.unit_map, raw_values)

        raw_path = self._current_raw_path(observed_at)
        write_envelope(raw_path, time.time(), self.adapter.protocol_id, frame)

        decoded = self.adapter.decode_response(frame)
        self._write_processed_layers(decoded, observed_at)

    def _compute_physics_value(self, asset: dict, observed_at: datetime) -> dict:
        """v3.1 physics_engine을 활용한 자산별 센서 및 물리 상태 관측치 산출."""
        from physics_engine import (
            coupled_cnc_values,
            ar_noise,
            operating_state,
            active_cnc_episode
        )

        asset_id = asset["asset_id"]
        runtime = self.runtimes[asset_id]
        episodes = self.episodes_by_asset.get(asset_id, [])

        is_operating_flag, operating_state_value = operating_state(episodes, observed_at)
        is_operating = bool(is_operating_flag)

        if asset["asset_type"] == "compressor":
            from physics_engine import (
                COMPRESSOR_BASELINE,
                GENERATOR_VERSION,
                sensor_effects,
                vibration_zone,
            )

            baseline = runtime.baseline
            effects = sensor_effects(episodes, observed_at)
            values = {}
            for sensor, (_mean, std) in COMPRESSOR_BASELINE.items():
                base = baseline[sensor]
                values[sensor] = (
                    base
                    + ar_noise(runtime, sensor, std)
                    + base * effects.get(sensor, 0.0)
                )
            vibration_std = float(COMPRESSOR_BASELINE["vibration_raw"][1])
            relative_vibration_z = (
                values["vibration_raw"] - baseline["vibration_raw"]
            ) / vibration_std
            return {
                "voltage_raw": round(values["voltage_raw"], 4),
                "rotation_raw": round(values["rotation_raw"], 4),
                "pressure_raw": round(values["pressure_raw"], 4),
                "vibration_raw": round(values["vibration_raw"], 4),
                "relative_vibration_z": round(relative_vibration_z, 4),
                "relative_vibration_zone": vibration_zone(relative_vibration_z),
                "is_operating": is_operating,
                "operating_state": operating_state_value,
                "generator_version": GENERATOR_VERSION,
            }
        else:
            # CNC 가공기
            is_operating, active_episode, protected_failure_window = self._prepare_cnc_runtime(
                runtime,
                episodes,
                observed_at,
                is_operating,
                active_cnc_episode,
            )
            res = coupled_cnc_values(runtime, episodes, observed_at)
            self._finish_cnc_runtime_cycle(
                runtime,
                observed_at,
                is_operating,
                active_episode,
                protected_failure_window,
            )
            from physics_engine import GENERATOR_VERSION

            return {
                "product_type": runtime.product_type,
                "air_temperature_k": round(res.get("air_temperature_k", 300.0), 2),
                "process_temperature_k": round(res.get("process_temperature_k", 310.0), 2),
                "rotational_speed_rpm": round(res.get("rotational_speed_rpm", 1500.0), 2),
                "torque_nm": round(res.get("torque_nm", 40.0), 2),
                "tool_wear_min": round(runtime.tool_wear_min, 2),
                "is_operating": is_operating,
                "operating_state": "running" if is_operating else "maintenance",
                "generator_version": GENERATOR_VERSION,
            }

    def _prepare_cnc_runtime(
        self,
        runtime,
        episodes: list,
        observed_at: datetime,
        is_operating: bool,
        active_cnc_episode,
    ) -> tuple[bool, object | None, bool]:
        """Canonical generator와 같은 순서로 CNC tick 직전 상태를 준비한다."""
        from physics_engine import choose_product, clamp

        tick = timedelta(minutes=int(self.config.GEN_DATA_INTERVAL_MINUTES))
        if runtime.tool_reset_at and observed_at >= runtime.tool_reset_at:
            runtime.tool_wear_min = runtime.rng.uniform(0.0, 4.0)
            runtime.tool_reset_at = None

        if runtime.planned_maintenance_until and observed_at < runtime.planned_maintenance_until:
            is_operating = False

        if runtime.product_started_at is None:
            runtime.product_started_at = observed_at
            runtime.product_type = choose_product(runtime)

        active_episode, active_ramp = active_cnc_episode(episodes, observed_at)
        protected_failure_window = bool(
            active_episode
            and str(active_episode.issue["component"]) in {"TWF", "OSF"}
        )
        if active_episode and protected_failure_window:
            signal_strength = float(active_episode.issue["signal_strength"])
            physical_ramp = clamp(
                active_ramp * (0.55 + 0.45 * signal_strength), 0.0, 1.0
            )
            if active_ramp >= 0.999:
                physical_ramp = 1.0
            if str(active_episode.issue["component"]) == "TWF":
                runtime.tool_wear_min = max(
                    runtime.tool_wear_min,
                    180.0 + 40.0 * physical_ramp,
                )
                if active_ramp >= 0.999:
                    runtime.tool_wear_min = max(runtime.tool_wear_min, 220.0)
            else:
                runtime.tool_wear_min = max(
                    runtime.tool_wear_min,
                    185.0 + 40.0 * physical_ramp,
                )
                if active_ramp >= 0.999:
                    runtime.tool_wear_min = max(runtime.tool_wear_min, 225.0)

        # Failure-recovery tool replacement starts at the same timestamp used
        # by the Canonical generator. The next tick applies the reset.
        for episode in episodes:
            if (
                observed_at <= episode.failure_at < observed_at + tick
                and str(episode.issue["component"]) in {"TWF", "OSF"}
            ):
                runtime.tool_reset_at = episode.maintenance_started_at

        return is_operating, active_episode, protected_failure_window

    def _finish_cnc_runtime_cycle(
        self,
        runtime,
        observed_at: datetime,
        is_operating: bool,
        active_episode,
        protected_failure_window: bool,
    ) -> None:
        """Canonical product-cycle 규칙으로 product/tool-wear 상태를 진행한다."""
        from physics_engine import (
            PRODUCT_CUTTING_MINUTES,
            TOOL_WEAR_EXPOSURE_FACTOR,
            choose_product,
        )

        interval_minutes = int(self.config.GEN_DATA_INTERVAL_MINUTES)
        product_cycle_minutes = int(
            getattr(self.config, "GEN_DATA_PRODUCT_CYCLE_MINUTES", 20)
        )
        product_ticks_target = max(1, product_cycle_minutes // interval_minutes)
        tick = timedelta(minutes=interval_minutes)

        if is_operating:
            runtime.product_ticks += 1
        if not is_operating or runtime.product_ticks < product_ticks_target:
            return

        cutting_min, cutting_max = PRODUCT_CUTTING_MINUTES[runtime.product_type]
        cutting_minutes = runtime.rng.uniform(cutting_min, cutting_max)
        runtime.tool_wear_min += cutting_minutes * TOOL_WEAR_EXPOSURE_FACTOR
        if active_episode and str(active_episode.issue["component"]) == "TWF":
            runtime.tool_wear_min = min(runtime.tool_wear_min, 220.0)

        runtime.product_counter += 1
        runtime.product_started_at = observed_at + tick
        runtime.product_ticks = 0
        runtime.product_type = choose_product(runtime)

        if (
            runtime.tool_wear_min >= runtime.tool_change_threshold_min
            and not protected_failure_window
        ):
            runtime.tool_reset_at = observed_at + tick
            runtime.planned_maintenance_until = observed_at + tick + timedelta(minutes=30)
            runtime.tool_change_threshold_min = runtime.rng.uniform(180.0, 235.0)

    def _write_processed_layers(self, decoded: dict, observed_at: datetime) -> None:
        """디코딩된 수치를 sensor 레이어 호환 CSV/JSON 파생 산출물로 기록."""
        sensor_dir = Path(self.config.GEN_DATA_OUTPUT_DIR) / "sensor" / f"fac{self.site_id}" / f"line{self.cell_id}"
        sensor_dir.mkdir(parents=True, exist_ok=True)

        ndjson_path = sensor_dir / "sensor_stream.jsonl"
        records = []
        for asset_id, values in decoded.items():
            record = {
                "asset_id": asset_id,
                "site_id": self.site_id,
                "cell_id": self.cell_id,
                "observed_at": observed_at.isoformat(),
                **values
            }
            records.append(record)

        with ndjson_path.open("a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
