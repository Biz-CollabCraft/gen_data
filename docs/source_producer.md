# Source Data Producer runtime

## Invariant

simulation 센서값은 `SimulationProducer`에서 한 번만 계산한다. 실제 OPC UA source는
SDK subscription에서 받은 DataValue를 재계산하지 않고 `SensorRecord`로 정규화한다.

```text
existing physics / sensor functions
        ↓
SimulationProducer
        ↓
SensorRecord
   ├─ SourceRecordWriter → source/sensor_records.jsonl
   ├─ OpcUaPublisher     → SDK DataValue + protocol provenance
   └─ CanonicalWriter    → 기존 canonical CSV contract

configured OPC UA Server
        ↓ asyncua subscription
OpcUaCollector
        ↓ reverse mapping / quality / timestamp
SensorRecord(source_kind=opcua)
   ├─ SourceRecordWriter → source/sensor_records.jsonl
   └─ ProtocolRecordWriter → received provenance / quarantine
```

writer나 protocol publisher는 physics 함수를 호출하지 않는다. protocol publish가 실패해도
이미 계산된 SensorRecord와 source/canonical projection은 유지된다.

## SensorRecord

필수 필드는 `schema_version`, `run_id`, `sequence`, `asset_id`, `observed_at`,
`measurements`, `generator_version`이다. 현재 canonical projection에 필요한
`asset_type`, `site_id`, `cell_id`도 함께 보존한다.

`observation_id`는 run 독립적인 결정론적 식별자다. 생성 시 `run_id`나
sequence를 포함하지 않으며 `asset_id`, `observed_at`, measurement fingerprint,
source kind를 기반으로 생성된다. Backend idempotency key로 사용할 수 있다.

`branch_kind`는 현재 모든 producer/collector 출력에서 `canonical`이다.
향후 overlay branch는 같은 observation contract를 유지하며 다음 형태의
optional `overlay` 객체를 사용한다.

```json
{
  "branch_kind": "overlay",
  "overlay": {
    "overlay_id": "...",
    "parent_branch": "canonical",
    "maintenance_event_id": "...",
    "state_patch_reference": "..."
  }
}
```

`sequence`는 run 안에서 yield된 record마다 증가한다. source correlation은
`run_id + sequence + asset_id`, protocol measurement correlation은 여기에
`measurement_key`를 더한다.

## OPC UA publisher

`app/protocol/opcua.py`는 `asyncua` SDK의 Server/Node/DataValue를 사용한다.
`mappings/opcua_nodes.v1.json`이 NodeId, DataType, unit을 결정하고
`SensorRecord.observed_at`을 OPC UA `SourceTimestamp`로 기록한다.

protocol provenance는 `run_id`, `sequence`, `asset_id`, `measurement_key`, `node_id`,
`data_type`, `unit`, `value`, `status_code`, `source_timestamp`, `published_at`,
`mapping_version`을 남긴다. 이것은 SDK publish provenance이지 wire packet capture가 아니다.

## OPC UA collector

같은 `app/protocol/opcua.py`의 `OpcUaCollector`는 configured endpoint/NodeId만 구독한다.
자동 browse/discovery나 범용 gateway를 만들지 않는다. versioned mapping template를
역으로 적용해 `asset_id`, `asset_type`, `measurement_key`, `unit`을 결정하고 수신된
DataValue 한 건을 measurement 하나를 가진 `SensorRecord(source_kind=opcua)`로 만든다.

수신 provenance는 publish provenance와 구별하기 위해 `direction=received`를 기록하며
`StatusCode`, `SourceTimestamp`, `ServerTimestamp`, `received_at`을 모두 보존한다.
`observed_at`은 SourceTimestamp → ServerTimestamp → received_at 순으로 선택한다.
SensorRecord에도 `observed_at_source` (`source` | `server` | `received`)를 함께 기록한다.
OPC UA quality는 source quality일 뿐 Diagnosis 상태로 해석하지 않는다.

현재 measurement 값은 기존 `measurements: dict[str, value]` 계약을 유지한다.
OPC UA 상태 코드와 quality metadata는 provenance boundary에 기록하며,
simulation과 OPC UA 모두 동일한 SensorRecord contract로 수렴한다.

최소 수집 안전장치는 다음과 같다.

- connection loss → reconnect → configured Node re-subscribe
- 같은 node/timestamp/value/status notification → in-process duplicate suppression
- unknown/ambiguous Node → quarantine
- mapping과 다른 DataType → quarantine
- server가 engineering unit property를 노출하고 mapping unit과 다름 → quarantine

collector는 SDK DataValue 수신 경계이며 wire packet capture가 아니다. PKI 자동화,
NodeSet 자동 discovery, multi-server federation, late-arrival aggregation은 현재 범위가 아니다.

## RuntimeManager / FastAPI

`RuntimeManager`가 run 중 producer, writers, OPC UA session, manifest를 소유한다.
simulation run의 manual tick과 continuous loop는 같은 `process_tick`을 사용한다.
`source_kind=opcua` run은 subscription worker를 소유하며 manual tick은 지원하지 않는다.
stop 시 writer flush와 OPC UA client/subscription cleanup을 수행한다.

FastAPI는 control layer만 담당한다.

```text
POST /api/runs
POST /api/runs/{run_id}/tick
POST /api/runs/{run_id}/stop
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/outputs
GET  /health/live
GET  /health/ready
```

### Top-level compatibility imports

현재 저장소 CI의 import/compile smoke가 아직 `api`, `daemon`, `line_worker`,
`protocol`, `state_tracker` top-level 경로를 확인한다. 이 경로들은 기존
Flask/daemon/raw protocol 구현을 유지하지 않고 새 canonical 구현의 타입만
re-export하는 최소 compatibility shim이다.

- `api.create_app` → `app.main.create_app`
- `daemon.RuntimeManager` → `app.runtime.manager.RuntimeManager`
- `line_worker.SimulationProducer` → `app.simulation.producer.SimulationProducer`
- `protocol.OpcUaPublisher` → `app.protocol.opcua.OpcUaPublisher`
- `state_tracker.RunState` → `app.runtime.state.RunState`

운영 entrypoint와 application code는 이 top-level shim을 사용하지 않는다. 기존
custom Modbus/OPC-UA-shaped frame encoder/decoder와 global daemon loop는 제거된 상태다.

## Outputs

```text
output/runs/{run_id}/
├── source/sensor_records.jsonl
├── protocol/provenance.jsonl
├── protocol/errors.jsonl
├── protocol/quarantine.jsonl
├── canonical/
│   ├── asset_master.csv
│   ├── asset_relation.csv
│   ├── compressor_sensor_observation.csv
│   ├── cnc_sensor_observation.csv
│   ├── cnc_production_cycle.csv
│   └── maintenance_event.csv
└── run_manifest.json
```

정적 Canonical V3.1 생성도 같은 `SimulationProducer`와 `CanonicalWriter`를 사용하므로
별도의 physics 재계산 경로를 갖지 않는다.
