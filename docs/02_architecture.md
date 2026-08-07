# gen_data — 02. 구조

## 디렉터리 구조 (확정본)

```
gen_data/
├── config.py                    # .env + setting.config 로딩
├── setting.config                # (선택) 생성 설정 파일. 없으면 config.py의 하드코딩된 기본값 사용
├── physics_engine.py             # v3.1 물리 공식을 gen_data 구조에 맞게 재구성
├── state_tracker.py              # 전역 last_tick 체크포인트 (재시작 복원용)
├── protocol/
│   ├── base_protocol.py          # ProtocolAdapter 인터페이스
│   ├── modbus_adapter.py         # Modbus TCP 인코더/디코더 (기본 프로토콜)
│   ├── opcua_adapter.py          # OPC-UA Binary 인코더/디코더
│   └── raw_envelope.py           # 프로토콜 무관 캡처 envelope
├── line_worker.py                # 라인 1개의 "한 tick 처리" 단위
├── daemon.py                     # 공유 타임라인 루프 + 라인 병렬 실행
├── daemon_state.py                # server.py ↔ daemon.py 간 스레드 공유 상태
├── server.py                      # FastAPI 제어 서버 (상태 조회/수동 tick/설정 변경)
├── run.py                        # CLI 진입점 — 데몬(메인 스레드) + server.py(별도 스레드) 함께 기동
├── docs/                          # 본 문서 3종
│   ├── 01_overview.md
│   ├── 02_architecture.md        # (본 파일)
│   └── 03_detailed_spec.md
├── .state/
│   └── gen_data_state.json       # {"last_tick": "..."}
└── output/
    └── raw/
        └── fac{site_id}/                    # 예: facS01
            └── line{cell_id}/               # 예: lineL01
                ├── line_unit_map.json        # {asset_id ↔ unit_id}, 라인마다 자동 생성
                ├── line_protocol_map.json     # (선택) 이 라인만 프로토콜 override 시에만 존재
                └── {YYYY-MM-DD}/
                    └── {HHMMSS}.raw           # 프로토콜 프레임 캡처
```

## 컴포넌트별 책임

| 파일 | 책임 |
|---|---|
| `config.py` | `GEN_DATA_OUTPUT_DIR`은 `.env`에 있으면 그 값을, 없거나 빈 값이면 기본 경로로 자동 폴백(에러 아님). 나머지 생성 설정(seed·interval·speed·protocol 등)은 `setting.config` 파일이 있으면 그 값을, 없으면 하드코딩된 기본값을 사용. 두 경우 모두 어떤 값을 썼는지(`OUTPUT_DIR_SOURCE`, `SETTINGS_SOURCE`)를 기동 로그에 남김 |
| `physics_engine.py` | v3.1 `scripts/generate_canonical_dataset.py`의 물리 공식(수식·조건)을 gen_data 구조에 맞게 재구성 — 파일을 그대로 가져다 쓰지 않음. v3.1은 초기 압축기·CNC 시뮬레이터 프로토타입이 개선을 거쳐 완성된 최종본이므로(§01 개요 "정체성" 참조), gen_data가 물리 공식의 근거로 삼는 소재지는 v3.1 하나로 확정되어 있다. 정합성은 값 비교 테스트로 확인(§03 상세 스펙) |
| `state_tracker.py` | 전역 `last_tick` 하나만 저장/조회 |
| `protocol/base_protocol.py` | `encode_response()`/`decode_response()` 인터페이스 정의 |
| `protocol/modbus_adapter.py` | 값 → Modbus TCP MBAP+PDU 프레임, 그 역 |
| `protocol/opcua_adapter.py` | 값 → OPC-UA DataValue(Value/StatusCode/SourceTimestamp/ServerTimestamp) 바이너리, 그 역 |
| `protocol/raw_envelope.py` | 프레임 앞에 캡처 시각+프로토콜 식별자를 붙여 `.raw`에 append |
| `line_worker.py` | 라인 하나의 자산들에 대해 "한 tick분" 물리 계산 → 인코딩 → 캡처 → 가공까지 수행 |
| `daemon.py` | 전체 자산을 라인 단위로 묶고, 공유 타임라인으로 매 tick마다 전 라인을 병렬 실행. `DaemonState`를 통해 `server.py`와 상태(현재 시각·배속·자산 수)를 공유하고, 수동 tick 트리거를 받으면 대기를 건너뜀 |
| `daemon_state.py` | `daemon.py` ↔ `server.py` 간 스레드 안전 공유 상태(`speed`, `interval_minutes`, `current_time`, `status` 등) 보관 |
| `server.py` | FastAPI 제어 서버. `/api/status`(상태 조회), `/api/cycle/next`(수동 tick), `/api/config`(런타임 설정 변경) 3개 엔드포인트 제공, `daemon.py`와 별도 스레드로 동시 기동 |
| `run.py` | `server.py`를 별도 스레드로 먼저 기동한 뒤, 메인 스레드에서 `daemon.run_forever()` 호출. SIGINT/SIGTERM 처리 |

## 데이터 흐름 (Tick 단위 처리 절차)

```
daemon.py의 while 루프가 tick 시각(current_time)을 하나 정함
        ↓ (ThreadPoolExecutor로 라인 수만큼 동시 제출)
line_worker.run_one_cycle(current_time)  ×  라인 개수 (병렬)
        │
        ├─ ① 물리 계산 (physics_engine 함수 호출, 라인 안의 자산 전부)
        ├─ ② 프로토콜 인코딩 (adapter.encode_response)
        ├─ ③ .raw 캡처 (raw_envelope.write_envelope)
        ├─ ④ 프로토콜 디코딩 (adapter.decode_response) — "call 후 가공"을 코드로 분리
        └─ ⑤ Layer 1/2 기록 (장비별 최신값 overwrite + 취합 로그 append)
        ↓ (전 라인 완료 대기 후)
daemon.py: state_tracker.set_global_last_tick() → 다음 tick으로 진행
```

## 프로토콜 선택 정책 (기본값 통일 및 예외 적용)

```
daemon.py 기동
    ↓
config.GEN_DATA_PROTOCOL 값으로 "기본 adapter" 하나 생성
  (이 값 자체는 §03 §1의 우선순위 규칙을 따름:
   setting.config에 GEN_DATA_PROTOCOL 키가 있으면 그 값, 없으면 하드코딩된 기본값 "modbus_tcp")
    ↓
각 line_worker가 자기 라인 폴더에 line_protocol_map.json이 있는지 확인
    ├─ 없음(기본) → 기본 adapter 사용, 전 라인 통일
    └─ 있음(예외) → 그 파일에 지정된 protocol로 override, 이 라인만 다르게 동작
      (line_protocol_map.json은 gen_data가 자동으로 만들지 않는다 —
       사용자가 해당 라인 폴더에 직접 배치했을 때만 존재한다)
```

## 캐시 및 상태 관리

`ontology_dashboard` 쪽 3종 캐시(`extraction_plan_cache.json`, `mapping_cache.json`, `topology_cache.json`)는 **Agent 판단 결과**를 캐싱하는 것이라 gen_data와는 무관하다 — 이 캐시들은 "가공" 단계(ontology_dashboard)에 속한다. gen_data가 갖는 유일한 상태 파일은 `.state/gen_data_state.json`이며, 이건 "판단 재사용"이 아니라 "데몬 재시작 시 시뮬레이션 시계를 어디서부터 이어갈지"를 위한 체크포인트다 — "생성" 단계(gen_data)와 "가공" 단계(ontology_dashboard)의 상태 파일은 성격이 다르므로 헷갈리지 않아야 한다.

## 라인(Line) 단위 정의

```
site(공장) × cell(라인) × (압축기 1대 + CNC 0~4대) = 하나의 "라인"
```

기획서 §3의 자산 계층(4 site × 5 cell × (압축기1+CNC4) = 100대, `SUPPLIES_AIR_TO` 80건)을 그대로 따른다. 라인 하나 = 실제 현장에서 게이트웨이/PLC 하나가 폴링을 담당하는 물리적 단위에 대응하며, 이게 `.raw` 파일을 라인 폴더 아래 두는 이유다(§01 개요의 "왜 라인별인가").
