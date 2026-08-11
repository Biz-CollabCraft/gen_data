# gen_data — 03. 구체적인 내용

> 구현 상태: `config.py`, protocol facade, worker, daemon, CLI는 현재 PR에 구현되어
> 있다. §8의 `DaemonState` 확장안과 §8-1 `server.py` 제어 API는 **후속 설계**이며
> 현재 파일/API로 존재하지 않는다.

## 1. `.env` 변수 정의

`.env`는 이제 생성 설정값을 직접 담지 않는다. 대신 **설정 파일 경로**와 **출력 경로**만 지정하고, 실제 생성 설정(seed, interval, speed 등)은 그 설정 파일이 있으면 그 파일을, 없으면 하드코딩된 기본값을 따른다.

```env
GEN_DATA_OUTPUT_DIR=/path/to/gen_data/output
GEN_DATA_SETTING_CONFIG_PATH=/path/to/gen_data/setting.config
```

| 변수 | 의미 | 비고 |
|---|---|---|
| `GEN_DATA_OUTPUT_DIR` | `.raw` 및 파생 산출물 저장 루트 | **미설정 또는 빈 값이면 저장소 루트의 `output/`로 자동 폴백** — 에러로 중단하지 않음. `OUTPUT_DIR_SOURCE`로 출처를 남긴다. |
| `GEN_DATA_SETTING_CONFIG_PATH` | 생성 설정 파일(`setting.config`)의 경로 | 미설정 또는 그 경로에 파일이 없으면 하드코딩된 기본값으로 동작 (에러 아님) |
| `GEN_DATA_API_HOST` / `GEN_DATA_API_PORT` | 후속 계획인 `server.py`용 설정 | 현재 PR의 실행 코드에서는 아직 사용하지 않음 |
| `GEN_DATA_SEED` | 시뮬레이션 난수 시드 값 (선택적 최우선 덮어쓰기) | `.env`/환경변수에 설정 시 최우선 적용. 정수(예: `42`) 지정 시 고정 시드, `"random"`, `"-1"`, `"none"` 지정 시 프로세스 시작 때 시스템 엔트로피로 새 정수 seed를 한 번 생성. 미지정 시 `setting.config` ➔ 기본값 `42` |

### `setting.config` 파일 형식

JSON 형식이며, 필요한 키만 부분적으로 채워도 된다 — 파일에 없는 키는 하드코딩된 기본값을 그대로 사용한다 (완전 대체가 아니라 병합).

```json
{
  "GEN_DATA_SEED": 42,
  "GEN_DATA_INTERVAL_MINUTES": 10,
  "GEN_DATA_SPEED": 60,
  "GEN_DATA_BACKFILL_HOURS": 6,
  "GEN_DATA_MAX_PARALLEL_LINES": 20,
  "GEN_DATA_PROTOCOL": "modbus_tcp"
}
```

### 우선순위 규칙

```
GEN_DATA_SETTING_CONFIG_PATH가 .env에 지정되어 있고, 그 경로에 파일이 실제로 존재한다
    → 그 파일의 값으로 생성 (파일에 없는 키는 하드코딩된 기본값으로 보충)
그렇지 않다 (경로 미지정 또는 파일 없음)
    → 하드코딩된 기본값(config.py의 DEFAULTS)으로 전부 생성
```

`GEN_DATA_OUTPUT_DIR`도 이 우선순위 규칙과 별개로 동작한다 — 다만 이전 버전과 달리 **미설정 시 에러가 아니라 기본 경로로 자동 폴백**된다(§3 `config.py` 참조). "생성 결과를 어디에 쓸지" 자체는 항상 결정되어야 하므로 이 값만은 항상 유효한 값(직접 지정 또는 기본값)을 갖도록 보장한다.

## 2. v3.1 데이터 관계도 및 파일별 상세 (공식 릴리스 기준)

`gen_data`가 실시간으로 재현하는 v3.1의 canonical 데이터 관계는 다음과 같다 (GitHub Release 노트 원본).

```
asset_master ──┬──▶ compressor observations
               ├──▶ cnc observations
               ├──▶ maintenance events
               ├──▶ prediction timeline
               └──▶ result artifacts

asset_relation ──(SUPPLIES_AIR_TO)──▶ asset_master

production cycles ──▶ asset_master

maintenance events ──(source_event_id, 점선)──▶ evaluation failure truth

prediction timeline ──▶ result artifacts
```

**Canonical source** (`gen_data`가 실시간 재현하려는 대상 — Truth/Observation 분리 원칙상 이 계층만 관측 가능해야 함):

| 파일 | 행 수 | 포함 데이터 | 조인 키 |
|---|---:|---|---|
| `asset_master.csv` | 100 | 자산 유형, 사이트, 셀 | `asset_id` |
| `asset_relation.csv` | 80 | 압축기 → CNC 공급 관계 | `from_asset_id`, `to_asset_id` |
| `compressor_sensor_observation.csv` | 86,400 | 전압, 회전, 압력, 진동, 상대 진동 zone | `asset_id`, `observed_at` |
| `cnc_sensor_observation.csv` | 345,600 | 공기·공정 온도, RPM, 토크, 공구 마모 | `asset_id`, `observed_at` |
| `cnc_production_cycle.csv` | 170,875 | 제품 유형, 절삭 시간, wear 증가량 | `cnc_asset_id` |
| `maintenance_event.csv` | 790 | 계획 공구 교체, 고장 복구 | `asset_id`, `source_event_id` |
| `dataset_manifest.json` | 1 | 기간, seed, 물리 계약, 파일 checksum | `dataset_version` |

**Evaluation truth** (gen_data가 알고 있어야 하지만 출력 파일에는 절대 노출하지 않는 계층 — §01 개요의 Truth/Observation 분리 원칙 그대로 적용):

| 파일 | 행 수 | 내용 |
|---|---:|---|
| `failure_schedule.csv` | 115 | 생성기에 입력한 잠재 고장 일정 |
| `compressor_failure_truth.csv` | 20 | 압력·베어링·구동·전기 고장 정답 |
| `cnc_failure_truth.csv` | 56 | PWF 14, HDF 21, OSF 11, TWF 6, RNF 4 |

**Derived model outputs** (V3.1 이관 당시 생성된 compatibility/reference/regression/migration fixture):

| 파일 | 행 수 | 내용 |
|---|---:|---|
| `prediction_snapshot.jsonl` | 100 | 자산별 최신 24시간 위험도 |
| `prediction_factor.jsonl` | 300 | 최신 예측별 Top-3 기여 factor |
| `prediction_timeline.jsonl` | 68,208 | Historical Replay용 시간별 위험도 |
| `result_artifact.jsonl` | 100 | Dashboard·Agent·Report 공통 결과 계약 |

실시간 `gen_data` daemon은 운영 Model/Prediction/Result Artifact를 생성하지 않는다.
위 Derived model outputs는 저장소에 보존된 **reference/regression/migration fixture**이며,
운영 Model Artifact producer는 `ontology_dashboard/systems/generator`, 운영 Product
Result Artifact/Evidence producer는 `ontology_dashboard/systems/backend/diagnosis`다.
세부 KEEP / REFERENCE FIXTURE / MIGRATE 분류는 루트
[`OWNERSHIP_AND_MIGRATION.md`](../OWNERSHIP_AND_MIGRATION.md)를 따른다. Evaluation truth는
계속 평가·검증 전용이며 제품 Dashboard/API/LLM 입력에 노출하지 않는다.

## 3. `config.py`

현재 `config.py`가 실제 계약의 기준이다.

- 외부 의존성 없이 저장소 루트 `.env`의 단순 `KEY=VALUE`를 읽는다.
- `GEN_DATA_OUTPUT_DIR`이 없거나 빈 값이면 저장소 루트의 `output/`로 폴백한다.
- `GEN_DATA_SETTING_CONFIG_PATH`가 없으면 저장소 루트의 `setting.config`를 찾는다.
- `setting.config`는 JSON object이며 `DEFAULTS`에 부분 병합된다.
- `GEN_DATA_SEED` 환경변수는 `setting.config`보다 우선한다.
- `random`, `-1`, `none`은 프로세스 시작 때 시스템 엔트로피로 새 정수 seed를 한 번
  생성한다. 한 실행 안에서는 모든 컴포넌트가 같은 정수 seed를 공유한다.
- `OUTPUT_DIR_SOURCE`, `SETTINGS_SOURCE`, `SEED_SOURCE`를 기동 로그에 노출한다.

`GEN_DATA_API_HOST`/`GEN_DATA_API_PORT`는 §8-1의 후속 제어 API가 구현될 때 추가할
설정이며 현재 `config.py`에는 존재하지 않는다.

## 4. `physics_engine.py` — Canonical V3.1 호환 facade

현재 구현은 v3.1의 검증된 물리 함수와 타입을 중복 복사하지 않고
repository root의 `scripts/generate_canonical_dataset.py`에서 import해 facade로 노출한다.
저장소 루트 자체가 기본 Canonical V3.1 기준본이며, 외부 baseline을 비교해야 하는
경우에만 `GEN_DATA_CANONICAL_ROOT`로 별도 루트를 지정한다.

아래 재구성 코드와 `test_physics_parity.py`는 초기 대안 설계를 보존한 참고 예시이며
**현재 runtime 구현이 아니다**. 현재 runtime은 위에서 설명한 import facade 방식이다.

```python
# gen_data/physics_engine.py — v3.1 SCHEMA.md/ARCHITECTURE_DECISION.md의 공식을 근거로 재구성
import math

# 아래 baseline·표준편차는 v3.1 CNC_BASELINE/COMPRESSOR_BASELINE 값을 그대로 채용 (출처 명시)
CNC_BASELINE = {"air_temperature_k": 300.0, "process_temperature_k": 310.0,
                 "rotational_speed_rpm": 1538.0, "torque_nm": 40.0}
AIR_PROCESS_COEFF = 0.68     # process ≈ baseline + 0.68 × air_deviation + residual
RPM_INVERSE_BLEND = 0.30     # rpm ≈ baseline + 0.30 × (ideal_rpm − baseline) + residual

def ideal_rpm_from_power(target_power_w: float, torque_nm: float) -> float:
    return target_power_w * 60 / (2 * math.pi * torque_nm)

def coupled_cnc_values(air_temperature_k: float, torque_nm: float, target_power_w: float,
                        residual_process: float, residual_rpm: float) -> dict:
    process_temperature_k = (
        CNC_BASELINE["process_temperature_k"]
        + AIR_PROCESS_COEFF * (air_temperature_k - CNC_BASELINE["air_temperature_k"])
        + residual_process
    )
    ideal_rpm = ideal_rpm_from_power(target_power_w, torque_nm)
    rotational_speed_rpm = (
        CNC_BASELINE["rotational_speed_rpm"]
        + RPM_INVERSE_BLEND * (ideal_rpm - CNC_BASELINE["rotational_speed_rpm"])
        + residual_rpm
    )
    return {"process_temperature_k": process_temperature_k, "rotational_speed_rpm": rotational_speed_rpm}
```

**공식 물리 계약** (GitHub Release 노트에 명시된 것 — 재구성 시 이 5줄을 정확히 만족해야 함):

```
power = torque × rpm × 2π / 60
PWF: power < 3,500W or power > 9,000W
HDF: process - air < 8.6K and rpm < 1,380
OSF: tool_wear × torque > L 11,000 / M 12,000 / H 13,000
TWF: tool_wear between 200 and 240 minutes
RNF: condition-independent random failure
```

### 정합성 검증 — 현재 facade 기준

현재 구현은 Canonical V3.1 함수를 직접 재사용하므로 별도의 재구성 parity가 merge
조건은 아니다. 아래 테스트 스케치는 초기 대안 설계 기록이며 현재 테스트 파일로
존재하지 않는다. PR #1에서는 Canonical 기준본을 지정한 상태의 import/export smoke
check를 수행하고, 데이터 자체의 검증·재현성은 PR #2의 validation script가 담당한다.

```python
# gen_data/tests/test_physics_parity.py (개발 시 1회성으로 실행, 런타임에는 실행하지 않음)
# v3.1 scripts/generate_canonical_dataset.py를 별도 프로세스로 참조 실행해
# 동일 seed·동일 입력값에 대해 gen_data.physics_engine의 재구성 결과와 오차 허용범위 내로 일치하는지 확인
def test_coupled_cnc_values_matches_v3_1_reference():
    ...  # 두 결과의 process_temperature_k, rotational_speed_rpm 차이가 1e-6 이내인지 assert
```

이 테스트 스케치는 현재 실행 대상이 아니다.

## 5. `state_tracker.py`

```python
import json
from pathlib import Path
from datetime import datetime

STATE_PATH = Path(__file__).parent / ".state" / "gen_data_state.json"

def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))

def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def get_global_last_tick(state: dict) -> datetime | None:
    raw = state.get("last_tick")
    return datetime.fromisoformat(raw) if raw else None

def set_global_last_tick(state: dict, observed_at: datetime) -> None:
    state["last_tick"] = observed_at.isoformat()
```

## 6. `protocol/` — 어댑터 인터페이스와 캡처 envelope

```python
# base_protocol.py
from abc import ABC, abstractmethod

class ProtocolAdapter(ABC):
    protocol_id: int

    @abstractmethod
    def encode_response(self, unit_or_node_map: dict, raw_values: dict) -> bytes: ...

    @abstractmethod
    def decode_response(self, frame: bytes) -> dict: ...
```

```python
# raw_envelope.py — 프로토콜 무관, pcap과 같은 방식(프레임 앞에 타임스탬프+식별자)
import struct
from pathlib import Path

PROTOCOL_MODBUS_TCP = 1
PROTOCOL_OPCUA_BINARY = 2

def write_envelope(raw_path: Path, capture_timestamp: float, protocol_id: int, frame: bytes) -> None:
    with raw_path.open("ab") as f:
        f.write(struct.pack(">dBI", capture_timestamp, protocol_id, len(frame)))
        f.write(frame)
```

**Modbus 어댑터**: MBAP 헤더(Transaction ID/Protocol ID/Length/Unit ID) + PDU(function code 0x03 + byte count + float32 big-endian 값들). 32비트 값의 byte order는 국제 표준으로 고정돼 있지 않으므로 big-endian(가장 흔한 관례)으로 명시 채택.

**OPC-UA 어댑터**: `DataValue` 구조(Value/StatusCode/SourceTimestamp) 그대로 인코딩. `SourceTimestamp`는 UA DateTime 규격(1601-01-01 기준 100ns 단위 정수)을 따른다. `StatusCode`는 기본 `Good(0)`이며, 통신 장애를 시뮬레이션할 경우에만 `Bad`로 채운다 — **StatusCode는 "값의 신뢰도"만 나타내고 "설비 건강 상태"와는 별개 개념**이라는 점이 확정 원칙이다 (설비 고장은 `Good` 상태를 유지한 채 값 자체의 이상 패턴으로만 나타나야 함).

**로그 압축 관행**: OPC-UA Part 11(Historical Access)이 명시적으로 허용하는 대로, 평상시(Good)에는 quality 필드를 생략하고 값만 기록하며, 상태가 바뀌는 순간에만 quality를 명시한다.

## 7. `line_worker.py` — 라인 1개, "한 tick" 처리

```python
class LineWorker:
    def __init__(self, site_id, cell_id, line_assets, runtimes, episodes_by_asset, config, default_adapter):
        ...
        self.adapter = self._resolve_adapter(default_adapter)  # override 있으면 그걸, 없으면 기본값
        self.unit_map = self._load_or_create_unit_map()

    def run_one_cycle(self, observed_at: datetime) -> None:
        raw_values = {a["asset_id"]: self._compute_physics_value(a, observed_at) for a in self.assets}
        frame = self.adapter.encode_response(self.unit_map, raw_values)
        write_envelope(self._current_raw_path(observed_at), time.time(), self.adapter.protocol_id, frame)
        decoded = self.adapter.decode_response(frame)
        self._write_processed_layers(decoded, observed_at)
```

`run_forever()`는 없다 — **언제 실행할지는 `daemon.py`의 책임**이고, `LineWorker`는 "주어진 시각 하나를 처리하는 방법"만 안다.

## 8. `daemon.py` — 공유 타임라인 + 병렬 실행

현재 구현은 고정된 `speed`/`interval_minutes`로 공유 타임라인을 병렬 실행한다.
아래 `DaemonState` 기반 런타임 제어는 **후속 설계이며 현재 runtime 구현이 아니다**.

```python
# gen_data/daemon_state.py (신규)
import threading
from datetime import datetime

class DaemonState:
    def __init__(self, speed: float, interval_minutes: int):
        self.lock = threading.Lock()
        self.speed = speed
        self.interval_minutes = interval_minutes
        self.current_time: datetime | None = None
        self.asset_count = 0
        self.status = "starting"  # starting | running | stopped
        self.manual_tick_event = threading.Event()  # server.py가 set() → 다음 tick 즉시 실행

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "status": self.status,
                "current_time": self.current_time.isoformat() if self.current_time else None,
                "speed": self.speed,
                "interval_minutes": self.interval_minutes,
                "asset_count": self.asset_count,
            }

    def update_config(self, speed: float | None = None, interval_minutes: int | None = None) -> None:
        with self.lock:
            if speed is not None:
                self.speed = speed
            if interval_minutes is not None:
                self.interval_minutes = interval_minutes
```

```python
# gen_data/daemon.py (변경 — DaemonState 반영)
def run_forever(daemon_state: DaemonState):
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    workers, current_time, state = build_workers_and_start_time()
    daemon_state.asset_count = sum(len(w.assets) for w in workers)
    daemon_state.status = "running"
    wall_clock_now = datetime.now(tz=timezone.utc)
    is_backfilling = current_time < wall_clock_now

    with ThreadPoolExecutor(max_workers=config.GEN_DATA_MAX_PARALLEL_LINES) as pool:
        while not _shutdown_event.is_set():
            futures = [pool.submit(w.run_one_cycle, current_time) for w in workers]
            wait(futures)
            for f in futures:
                f.result()

            daemon_state.current_time = current_time  # 상태 갱신 — /api/status가 이 값을 그대로 반환
            set_global_last_tick(state, current_time)
            save_state(state)

            tick = timedelta(minutes=daemon_state.interval_minutes)  # 매 tick마다 최신값 조회 (런타임 변경 반영)
            current_time += tick
            if is_backfilling and current_time >= wall_clock_now:
                is_backfilling = False

            if not is_backfilling:
                real_seconds_per_tick = (daemon_state.interval_minutes * 60) / daemon_state.speed
                triggered_early = daemon_state.manual_tick_event.wait(timeout=real_seconds_per_tick)
                if triggered_early:
                    daemon_state.manual_tick_event.clear()  # POST /api/cycle/next로 깨어난 경우

    daemon_state.status = "stopped"
```

**타임라인이 하나뿐인 이유**: 모든 라인이 같은 `current_time`을 공유하고, 그 시각에 대한 처리를 동시에 실행한다. 실제 공장은 라인마다 clock이 미묘하게 다를 수 있지만(§별도 논의에서 확인된 실제와의 차이), 이번 gen_data는 **"동일 타임라인 가정 하의 병렬 저장"**을 설계 목표로 명시적으로 채택했다 — 실제 현장 재현이 아니라 이 가정 위에서의 구현임을 문서에 남긴다.

## 8-1. `server.py` — FastAPI 제어 서버 (후속 계획, 현재 미구현)

아래 내용은 후속 구현 목표다. 현재 PR에는 `server.py`와 `daemon_state.py`가 없으며,
`run.py`는 데몬만 실행한다.

```python
# gen_data/server.py
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="gen_data control API")
_daemon_state = None  # run.py가 기동 시 주입

class ConfigUpdateRequest(BaseModel):
    speed: float | None = None
    interval_minutes: int | None = None

@app.get("/api/status")
def get_status():
    """데몬 동작 상태, 현재 시뮬레이션 시각, 배속, 생성된 자산 수를 반환."""
    return _daemon_state.snapshot()

@app.post("/api/cycle/next")
def trigger_next_cycle():
    """인터벌 대기를 건너뛰고 다음 tick을 즉시 실행."""
    _daemon_state.manual_tick_event.set()
    return {"triggered": True}

@app.post("/api/config")
def update_config(req: ConfigUpdateRequest):
    """speed/interval_minutes를 런타임에 동적으로 변경. 다음 tick부터 반영됨."""
    _daemon_state.update_config(speed=req.speed, interval_minutes=req.interval_minutes)
    return _daemon_state.snapshot()

def run_server(daemon_state, host: str, port: int):
    global _daemon_state
    _daemon_state = daemon_state
    uvicorn.run(app, host=host, port=port, log_level="warning")
```

```python
# gen_data/run.py (변경 — 서버 스레드 + 데몬을 함께 기동)
import threading
from gen_data.daemon import run_forever
from gen_data.daemon_state import DaemonState
from gen_data.server import run_server
import gen_data.config as config

def main():
    daemon_state = DaemonState(speed=config.GEN_DATA_SPEED, interval_minutes=config.GEN_DATA_INTERVAL_MINUTES)

    server_thread = threading.Thread(
        target=run_server,
        args=(daemon_state, config.GEN_DATA_API_HOST, config.GEN_DATA_API_PORT),
        daemon=True,  # 메인 스레드(데몬) 종료 시 서버도 함께 종료
    )
    server_thread.start()

    run_forever(daemon_state)  # 메인 스레드는 데몬 루프

if __name__ == "__main__":
    main()
```

**엔드포인트 3종 요약**

| 엔드포인트 | 메서드 | 기능 |
|---|---|---|
| `/api/status` | GET | 데몬 상태(`status`), 현재 시뮬레이션 시각(`current_time`), 배속(`speed`), 생성된 자산 수(`asset_count`) 반환 |
| `/api/cycle/next` | POST | 인터벌 대기 없이 다음 tick을 즉시 생성·파일 append |
| `/api/config` | POST | `speed`/`interval_minutes`를 런타임에 동적 변경 (다음 tick부터 반영) |

## 9. 실행 방법

```bash
cd /path/to/gen_data
# 외부 Canonical baseline과 비교해야 할 때만 선택적으로 지정
export GEN_DATA_CANONICAL_ROOT=/path/to/external/gen_data
python run.py
```

기동 로그에는 `OUTPUT_DIR_SOURCE`, `SETTINGS_SOURCE`, `SEED_SOURCE`가 함께 표시된다.
기본값은 현재 repository root이므로 일반 실행에서는 `GEN_DATA_CANONICAL_ROOT`를
지정하지 않는다.

## 10. Acceptance Criteria (통합)

| # | 기준 |
|---|---|
| 1 | `GEN_DATA_OUTPUT_DIR` 미설정/빈 값이어도 저장소 루트 `output/`로 폴백하고 `OUTPUT_DIR_SOURCE`가 남음 |
| 2 | repository root의 Canonical V3.1 기준본 또는 명시적 `GEN_DATA_CANONICAL_ROOT`를 사용해 `physics_engine.py` facade가 정상 import됨 |
| 3 | 라인 폴더가 자산 그룹 수(최대 20)만큼 생성, 각 라인 폴더에 `line_unit_map.json` 자동 생성 |
| 4 | 같은 tick의 모든 라인 `.raw` 파일명(`{HHMMSS}.raw`)이 정확히 동일한 시각으로 생성 |
| 5 | 전 라인 처리 시간이 "라인 수 × 단일 라인 처리시간"이 아니라 "단일 라인 처리시간"에 근접 (병렬성 검증) |
| 6 | `line_protocol_map.json` 없는 라인은 전부 `GEN_DATA_PROTOCOL` 사용, 있는 라인만 override |
| 7 | `GEN_DATA_OUTPUT_DIR` 하위 어떤 파일에도 `failure_mode`/`degradation_started_at` 등 정답 컬럼 없음 (Truth/Observation 분리 검증) |
| 8 | 데몬 재시작 시 `gen_data_state.json`의 `last_tick` 다음부터 중복 없이 이어짐 |
| 9 | 최초 기동 시 `GEN_DATA_BACKFILL_HOURS`만큼 지연 없이 즉시 채워짐 |
| 10 | `GEN_DATA_SETTING_CONFIG_PATH`가 가리키는 파일이 실제 존재하면, 그 파일의 값(부분 키만 있어도)이 하드코딩된 기본값보다 우선 적용됨 |
| 11 | `GEN_DATA_SETTING_CONFIG_PATH` 미설정이거나 파일이 없으면, 에러 없이 하드코딩된 기본값(`config.DEFAULTS`)으로 정상 기동됨 |
| 12 | **후속 계획**: `GET /api/status`가 실제 데몬 상태와 일치 |
| 13 | **후속 계획**: `POST /api/cycle/next`가 인터벌 대기를 깨우고 다음 tick을 실행 |
| 14 | **후속 계획**: `POST /api/config`의 runtime speed 변경을 다음 tick부터 반영 |

## 11. Non-Goals

- Modbus/OPC-UA 외 추가 프로토콜(MQTT 등) — 인터페이스는 확장 가능하게 열려 있으나 이번 범위는 2종까지
- 라인 간 서로 다른 clock/네트워크 지연 시뮬레이션 — §7에서 명시한 대로 "동일 타임라인" 가정을 의도적으로 채택
- 여러 gen_data 인스턴스의 분산 실행/failover
- **별도 데이터 증강(augmentation) 모듈** — 검토 단계에 있었으나 최종 설계에서 제외됨. gen_data(.raw 생성) → ontology_dashboard(가공·사용)의 2단 구조로 확정하며, 그 사이에 별도 augmenter 단계는 두지 않는다 (§01 개요 "저장소 구조" 참조)
- `.raw`를 다시 읽어 Feature로 변환하는 부분(Decode Schema Agent, byte stream reader, `data/sensor`·`data/result` 변환) — 이건 "가공·사용" 담당인 `ontology_dashboard` 쪽 작업이며, 그 경로 계약은 §01 개요 "데이터 경로 계약"에서 정의하고 세부 구현은 별도 문서(Data-to-Feature 플랫폼 문서)에서 다룸

## 12. 미결 사항 (다음 세션 확정 필요)

1. **제어 API 구현 여부 확정** — 현재 미구현인 `daemon_state.py`/`server.py`를 후속 PR에서 구현할지, 문서에서 장기 계획으로만 유지할지 팀 결정 필요
2. Topology 소스 파일 준비 방식(Case A: 구조화 파일 vs Case B: Agent 추론) — gen_data가 만드는 `line_unit_map.json`이 Case A의 `asset_master.csv`/`asset_relation.csv` 역할을 일부 대신할 수 있는지 검토
3. `.agents/` 설정 개선안(판단 분리 원칙) 실제 파일 반영 여부 — gen_data는 Agent가 없어 직접 대상은 아니지만, 이후 decode agent 작업 시 필요

## 13. 참고 자료

- **gen_data·ontology_dashboard 소속 조직**: GitHub Organization `Biz-CollabCraft` — 두 repo가 나란히 존재하며, 로컬에서는 `C:\kosa\project\final\gen_data\`, `C:\kosa\project\final\ontology_dashboard\`로 각각 clone되어 파일시스템으로만 연결됨 (§01 개요 "저장소 구조" 참조)
- **v3.1 물리 공식의 참고 출처** (Biz-CollabCraft와는 별개): GitHub 릴리스 `oosuhada/agentic-ontology-dashboard`, 태그 `predictive-maintenance-canonical-v3.1-20260805`, 커밋 `081f56d`
- Data Guide(브랜치 `docs/canonical-v3.1-release-data-guide`): `docs/10-product/predictive-maintenance-canonical-v3.1-data-guide.md` — 파일별 필드, 조인 규칙, Agent benchmark 상세는 이 문서 참조
- gen_data(생성) → ontology_dashboard(가공·사용)의 데이터 경로 계약(`GEN_DATA_OUTPUT_DIR/raw/` → `ontology_dashboard/data/sensor/` → `ontology_dashboard/data/result/*.npy`)은 §01 개요 "데이터 경로 계약" 참조
