# Source Data Producer runtime

## Invariant

센서값은 `SimulationProducer`에서 한 번만 계산한다.

```text
existing physics / sensor functions
        ↓
SimulationProducer
        ↓
SensorRecord
   ├─ SourceRecordWriter → source/sensor_records.jsonl
   ├─ OpcUaPublisher     → SDK DataValue + protocol provenance
   └─ CanonicalWriter    → 기존 canonical CSV contract
```

writer나 protocol publisher는 physics 함수를 호출하지 않는다. protocol publish가 실패해도
이미 계산된 SensorRecord와 source/canonical projection은 유지된다.

## SensorRecord

필수 필드는 `schema_version`, `run_id`, `sequence`, `asset_id`, `observed_at`,
`measurements`, `generator_version`이다. 현재 canonical projection에 필요한
`asset_type`, `site_id`, `cell_id`도 함께 보존한다.

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

실제 설비 endpoint subscription, DataValue 수신, reverse mapping, collector reconnect는
현재 runtime에 구현하지 않는다.

## RuntimeManager / FastAPI

`RuntimeManager`가 run 중 producer, writers, OPC UA session, manifest를 소유한다.
manual tick과 continuous loop 모두 같은 `process_tick`을 사용하고 stop 시 writer flush와
OPC UA cleanup을 수행한다.

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
