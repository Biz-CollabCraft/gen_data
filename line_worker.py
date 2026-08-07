# ──────────────────────────────────────────────
# 단일 라인 1개 틱 주기 처리 워커 모듈
# ──────────────────────────────────────────────

import json
import time
from datetime import datetime
from pathlib import Path

from gen_data.protocol.raw_envelope import write_envelope

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
        default_adapter
    ):
        self.site_id = str(site_id)
        self.cell_id = str(cell_id)
        self.assets = line_assets
        self.runtimes = runtimes
        self.episodes_by_asset = episodes_by_asset
        self.config = config

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
        raw_values = {a["asset_id"]: self._compute_physics_value(a, observed_at) for a in self.assets}
        frame = self.adapter.encode_response(self.unit_map, raw_values)

        raw_path = self._current_raw_path(observed_at)
        write_envelope(raw_path, time.time(), self.adapter.protocol_id, frame)

        decoded = self.adapter.decode_response(frame)
        self._write_processed_layers(decoded, observed_at)

    def _compute_physics_value(self, asset: dict, observed_at: datetime) -> dict:
        """v3.1 physics_engine을 활용한 자산별 센서 및 물리 상태 관측치 산출."""
        from gen_data.physics_engine import (
            coupled_cnc_values,
            ar_noise,
            operating_state,
            active_cnc_episode
        )

        asset_id = asset["asset_id"]
        runtime = self.runtimes[asset_id]
        episodes = self.episodes_by_asset.get(asset_id, [])

        is_operating_flag, mode_str = operating_state(episodes, observed_at)
        is_operating = bool(is_operating_flag)
        ep, ramp = active_cnc_episode(episodes, observed_at) if is_operating else (None, 0.0)

        if asset["asset_type"] == "compressor":
            baseline = runtime.baseline
            v_val = baseline["voltage_raw"] + ar_noise(runtime, "voltage_raw", 2.0)
            rot_val = baseline["rotation_raw"] + ar_noise(runtime, "rotation_raw", 10.0)
            p_val = baseline["pressure_raw"] + ar_noise(runtime, "pressure_raw", 0.5)
            vib_val = baseline["vibration_raw"] + ar_noise(runtime, "vibration_raw", 0.2)
            return {
                "voltage_raw": round(v_val, 2),
                "rotation_raw": round(rot_val, 2),
                "pressure_raw": round(p_val, 2),
                "vibration_raw": round(vib_val, 2),
                "is_operating": is_operating,
            }
        else:
            # CNC 가공기
            res = coupled_cnc_values(runtime, episodes, observed_at)
            return {
                "product_type": res.get("product_type", "M"),
                "air_temperature_k": round(res.get("air_temperature_k", 300.0), 2),
                "process_temperature_k": round(res.get("process_temperature_k", 310.0), 2),
                "rotational_speed_rpm": round(res.get("rotational_speed_rpm", 1500.0), 2),
                "torque_nm": round(res.get("torque_nm", 40.0), 2),
                "tool_wear_min": round(res.get("tool_wear_min", 0.0), 2),
                "is_operating": is_operating,
            }

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
