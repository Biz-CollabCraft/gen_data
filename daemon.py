# ──────────────────────────────────────────────
# 공유 타임라인 병렬 실행 데몬 모듈
# ──────────────────────────────────────────────

import random
import hashlib
import json
import signal
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from physics_engine import (
    build_topology,
    build_schedule,
    build_episodes,
    make_baseline,
    Runtime,
    stable_seed
)
from protocol.modbus_adapter import ModbusTcpAdapter
from protocol.opcua_adapter import OpcUaBinaryAdapter
from line_worker import LineWorker
from runtime_overlay import RuntimeOverlayCoordinator
from state_tracker import (
    load_state,
    save_state,
    get_global_last_tick,
    set_global_last_tick
)

PROTOCOL_ADAPTERS = {
    "modbus_tcp": ModbusTcpAdapter,
    "opcua_binary": OpcUaBinaryAdapter
}

_shutdown_event = threading.Event()


# ──────────────────────────────────────────────
# 종료 시그널 핸들러
# ──────────────────────────────────────────────

def _handle_shutdown(signum, frame):
    """종료 시그널 수신 시 이벤트를 설정하여 루프 정지."""
    _shutdown_event.set()


# ──────────────────────────────────────────────
# 라인별 자산 그룹화
# ──────────────────────────────────────────────

def group_assets_by_line(assets: list[dict]) -> dict:
    """사이트 및 셀 번호를 기준으로 라인별 자산 그룹화."""
    lines = {}
    for a in assets:
        key = (a["site_id"], a["cell_id"])
        lines.setdefault(key, []).append(a)
    return lines


# ──────────────────────────────────────────────
# 워커 객체 구축 및 시작 시각 산출
# ──────────────────────────────────────────────

def build_workers_and_start_time():
    """토폴로지 및 에피소드 구축 후 전 라인 워커 리스트 생성."""
    assets, relations = build_topology()
    schedule = build_schedule(assets, config.GEN_DATA_SEED, "balanced_demo")
    state = load_state()

    tick = timedelta(minutes=config.GEN_DATA_INTERVAL_MINUTES)
    last_tick = get_global_last_tick(state)
    current_time = (last_tick + tick) if last_tick else (
        datetime.now(tz=timezone.utc) - timedelta(hours=config.GEN_DATA_BACKFILL_HOURS)
    )

    far_future = current_time + timedelta(days=365)
    episodes = build_episodes(
        schedule,
        current_time - timedelta(hours=config.GEN_DATA_BACKFILL_HOURS),
        far_future,
        config.GEN_DATA_INTERVAL_MINUTES
    )
    episodes_by_asset = {}
    for ep in episodes:
        episodes_by_asset.setdefault(ep.issue["asset_id"], []).append(ep)

    runtimes = {
        a["asset_id"]: Runtime(
            asset=a,
            rng=random.Random(stable_seed(config.GEN_DATA_SEED, a["asset_id"], "runtime")),
            baseline=make_baseline(a, config.GEN_DATA_SEED)
        ) for a in assets
    }

    import line_worker as line_worker_module
    line_worker_module.PROTOCOL_ADAPTERS = PROTOCOL_ADAPTERS

    default_adapter_cls = PROTOCOL_ADAPTERS.get(config.GEN_DATA_PROTOCOL, ModbusTcpAdapter)

    workers = [
        LineWorker(site_id, cell_id, line_assets, runtimes, episodes_by_asset, config, default_adapter_cls())
        for (site_id, cell_id), line_assets in group_assets_by_line(assets).items()
    ]
    return workers, current_time, state, assets, runtimes


def _build_runtime_overlay(assets, runtimes):
    """Build the optional local/demo Runtime Overlay adapter."""
    event_file = config.GEN_DATA_RUNTIME_OVERLAY_EVENT_FILE
    if not event_file:
        return None

    manifest_path = Path(__file__).resolve().parent / "canonical" / "dataset" / "dataset_manifest.json"
    dataset_version = "predictive-maintenance-canonical-v3.1"
    base_source_sha256 = "unavailable"
    if manifest_path.exists():
        manifest_bytes = manifest_path.read_bytes()
        base_source_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        try:
            dataset_version = str(json.loads(manifest_bytes)["dataset_version"])
        except (KeyError, TypeError, json.JSONDecodeError):
            pass

    return RuntimeOverlayCoordinator(
        assets=assets,
        canonical_runtimes=runtimes,
        interval_minutes=config.GEN_DATA_INTERVAL_MINUTES,
        product_cycle_minutes=config.GEN_DATA_PRODUCT_CYCLE_MINUTES,
        output_root=Path(config.GEN_DATA_OUTPUT_DIR),
        base_dataset_version=dataset_version,
        base_source_sha256=base_source_sha256,
    )


def _process_runtime_overlay_events(overlay: RuntimeOverlayCoordinator) -> None:
    """Consume the configured JSONL inbox; idempotency makes rereads safe."""
    path = Path(str(config.GEN_DATA_RUNTIME_OVERLAY_EVENT_FILE))
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Runtime Overlay event JSON at {path}:{line_number}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"Runtime Overlay event must be an object at {path}:{line_number}")
        overlay.process_event(event)


# ──────────────────────────────────────────────
# 데몬 영구 실행 루프
# ──────────────────────────────────────────────

def run_forever():
    """공유 타임라인 기반 단일 무한 루프 데몬 구동."""
    try:
        signal.signal(signal.SIGINT, _handle_shutdown)
        signal.signal(signal.SIGTERM, _handle_shutdown)
    except (ValueError, AttributeError):
        pass

    workers, current_time, state, assets, runtimes = build_workers_and_start_time()
    runtime_overlay = _build_runtime_overlay(assets, runtimes)
    if runtime_overlay is not None:
        for worker in workers:
            worker.observation_allowed = runtime_overlay.canonical_observation_allowed
    tick = timedelta(minutes=config.GEN_DATA_INTERVAL_MINUTES)
    real_seconds_per_tick = (config.GEN_DATA_INTERVAL_MINUTES * 60) / config.GEN_DATA_SPEED
    wall_clock_now = datetime.now(tz=timezone.utc)
    is_backfilling = current_time < wall_clock_now

    print(
        f"gen_data 데몬 시작 — 라인 {len(workers)}개, 기본 프로토콜={config.GEN_DATA_PROTOCOL} "
        f"(line_protocol_map.json이 있는 라인만 override), 동일 타임라인으로 매 tick 병렬 저장; "
        f"output={config.OUTPUT_DIR_SOURCE}, settings={config.SETTINGS_SOURCE}, seed={config.SEED_SOURCE}"
    )

    with ThreadPoolExecutor(max_workers=config.GEN_DATA_MAX_PARALLEL_LINES) as pool:
        while not _shutdown_event.is_set():
            if runtime_overlay is not None:
                _process_runtime_overlay_events(runtime_overlay)

            # 이번 tick(current_time)을 모든 라인이 동시에 처리 — 같은 타임스탬프로 파일 병렬 저장
            futures = [pool.submit(w.run_one_cycle, current_time) for w in workers]
            wait(futures)
            for f in futures:
                f.result()  # 예외 즉시 확인 및 노출

            if runtime_overlay is not None:
                for equipment_id in runtime_overlay.active_equipment_ids:
                    _rows, available = runtime_overlay.advance_branch_to(
                        equipment_id, current_time
                    )
                    if available is not None:
                        runtime_overlay.persist_available_event(available)

            set_global_last_tick(state, current_time)
            save_state(state)

            current_time += tick
            if is_backfilling and current_time >= wall_clock_now:
                is_backfilling = False
            if not is_backfilling:
                time.sleep(real_seconds_per_tick)

    print("gen_data 데몬 정상 종료")
