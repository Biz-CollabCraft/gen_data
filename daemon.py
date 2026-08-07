# ──────────────────────────────────────────────
# 공유 타임라인 병렬 실행 데몬 모듈
# ──────────────────────────────────────────────

import random
import signal
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone

import gen_data.config as config
from gen_data.physics_engine import (
    build_topology,
    build_schedule,
    build_episodes,
    make_baseline,
    Runtime,
    stable_seed
)
from gen_data.protocol.modbus_adapter import ModbusTcpAdapter
from gen_data.protocol.opcua_adapter import OpcUaBinaryAdapter
from gen_data.line_worker import LineWorker
from gen_data.state_tracker import (
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

    import gen_data.line_worker as line_worker_module
    line_worker_module.PROTOCOL_ADAPTERS = PROTOCOL_ADAPTERS

    default_adapter_cls = PROTOCOL_ADAPTERS.get(config.GEN_DATA_PROTOCOL, ModbusTcpAdapter)

    workers = [
        LineWorker(site_id, cell_id, line_assets, runtimes, episodes_by_asset, config, default_adapter_cls())
        for (site_id, cell_id), line_assets in group_assets_by_line(assets).items()
    ]
    return workers, current_time, state


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

    workers, current_time, state = build_workers_and_start_time()
    tick = timedelta(minutes=config.GEN_DATA_INTERVAL_MINUTES)
    real_seconds_per_tick = (config.GEN_DATA_INTERVAL_MINUTES * 60) / config.GEN_DATA_SPEED
    wall_clock_now = datetime.now(tz=timezone.utc)
    is_backfilling = current_time < wall_clock_now

    print(
        f"gen_data 데몬 시작 — 라인 {len(workers)}개, 기본 프로토콜={config.GEN_DATA_PROTOCOL} "
        f"(line_protocol_map.json이 있는 라인만 override), 동일 타임라인으로 매 tick 병렬 저장"
    )

    with ThreadPoolExecutor(max_workers=config.GEN_DATA_MAX_PARALLEL_LINES) as pool:
        while not _shutdown_event.is_set():
            # 이번 tick(current_time)을 모든 라인이 동시에 처리 — 같은 타임스탬프로 파일 병렬 저장
            futures = [pool.submit(w.run_one_cycle, current_time) for w in workers]
            wait(futures)
            for f in futures:
                f.result()  # 예외 즉시 확인 및 노출

            set_global_last_tick(state, current_time)
            save_state(state)

            current_time += tick
            if is_backfilling and current_time >= wall_clock_now:
                is_backfilling = False
            if not is_backfilling:
                time.sleep(real_seconds_per_tick)

    print("gen_data 데몬 정상 종료")
