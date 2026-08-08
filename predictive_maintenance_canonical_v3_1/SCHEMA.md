# Predictive Maintenance Canonical V3.1 Schema

이 문서는 V3.1 패키지의 데이터 계층과 파일별 역할을 정의한다. 원천 관측,
평가용 정답, 모델 파생 결과, 에이전트 실험 자산을 서로 다른 계약으로
관리한다.

## 1. Canonical source

경로: `canonical/dataset/`

### `asset_master.csv`

| 필드 | 타입 | 설명 |
|---|---|---|
| `asset_id` | string | 자산 고유 ID |
| `asset_type` | enum | `compressor`, `cnc` |
| `site_id` | string | 사이트 ID |
| `cell_id` | string | 생산 셀 ID |

### `asset_relation.csv`

| 필드 | 타입 | 설명 |
|---|---|---|
| `from_asset_id` | string | 관계 시작 자산 |
| `relation_type` | enum | 현재 `SUPPLIES_AIR_TO` |
| `to_asset_id` | string | 관계 대상 자산 |

`SUPPLIES_AIR_TO`는 설비 구성 관계이며 인과 정답이 아니다.

### `compressor_sensor_observation.csv`

시간, 자산·사이트·셀, 운전 상태와 다음 압축기 관측값을 포함한다.

- `voltage_raw`
- `rotation_raw`
- `pressure_raw`
- `vibration_raw`
- `relative_vibration_z`
- `relative_vibration_zone`

### `cnc_sensor_observation.csv`

시간, 자산·사이트·셀, 운전 상태, 제품 유형과 다음 CNC 관측값을 포함한다.

- `air_temperature_k`
- `process_temperature_k`
- `rotational_speed_rpm`
- `torque_nm`
- `tool_wear_min`

V3.1에서는 air/process와 rpm/torque를 독립 생성하지 않는다. 정상 RPM은
`baseline_rpm + 0.30 × (ideal_rpm - baseline_rpm) + residual`로 생성하며,
`ideal_rpm = power_target × 60 / (2π × torque)`다.

PWF low-power branch는 목표 전력을 3,200W로 설정하기 전에 torque를 34Nm
방향으로 사전 조정한다. 이렇게 하면 지원 RPM 범위 안에서 정확한 전력식을
만족할 수 있다. 이후 RPM은 조정된 torque와 목표 전력으로 역산한다.

### `cnc_production_cycle.csv`

제품 ID, CNC ID, cycle 시작·완료 시각, 제품 유형, 절삭 시간, tool-wear
증분을 기록한다.

### `maintenance_event.csv`

계획 공구 교체와 고장 복구 정비를 기록한다. 고장 복구는
`source_event_id`로 evaluation truth와 연결된다.

`tool_replaced=1`이면 공구 마모 초기화는 반드시 `started_at`과 같은 CNC
sensor tick에서 발생하며 그 행은 `operating_state=maintenance`다. 가동 중
연속된 두 행 사이에서 1분을 초과하는 공구 마모 감소는 허용하지 않는다.

### `dataset_manifest.json`

생성 버전, 기간, seed, 생성 profile, AI4I 물리 계약, 파일 SHA-256을 기록한다.

## 2. Evaluation truth

경로: `canonical/evaluation_truth/`

- `failure_schedule.csv`: 생성기에 입력되는 숨은 고장 일정
- `compressor_failure_truth.csv`: 압축기 고장 이벤트 정답
- `cnc_failure_truth.csv`: CNC 고장 이벤트 정답과 AI4I condition variant

이 파일은 label 생성·검증 전용이다. Canonical feature 또는 공개 agent
입력으로 사용하지 않는다.

## 3. Derived model outputs

경로: `canonical/model_outputs/`

- `prediction_snapshot.jsonl`: 자산별 최신 위험도
- `prediction_factor.jsonl`: 최신 예측의 Top-3 기여 factor
- `prediction_timeline.jsonl`: replay용 시간별 out-of-fold 위험도
- `result_artifact.jsonl`: 대시보드·에이전트·보고서 공통 결과 계약
- `model_metrics.json`: leave-one-site-out sanity benchmark
- `model_contract.json`: 입력·출력 checksum 및 모델 계약

모델 결과는 canonical source에 역기입하지 않는다.

## 4. Optional agent benchmark

경로: `experiments/connected_air_supply/`

- `public_cases/`: 에이전트가 읽는 관측·관계 데이터
- `public_case_index.csv`: 공개 case 목록
- `hidden_truth/scenario_truth.csv`: 평가기 전용 정답
- `experiment_manifest.json`: positive/negative case 수와 checksum

V3.1 benchmark는 다음 두 유형을 포함한다.

- `positive_upstream_relation`: 상류 압축기 변화와 하류 CNC 변화가 함께 존재
- `negative_local_only`: CNC 자체 변화만 존재하고 상류 압축기는 canonical 상태 유지

## 5. Validation outputs

경로: `canonical/validation/`

- `package_validation.json`: 구조·checksum·AI4I 물리·failure 조건 검증
- `reproducibility_validation.json`: 동일 seed 결정성 및 다른 seed 변화 검증
- `agent_claims_example_evaluation.json`: positive/negative evaluator smoke 결과

Agent evidence는 `evidence_type=sensor|maintenance`를 사용한다. Maintenance
evidence는 canonical maintenance ID, asset, type, start/completion time,
`tool_replaced`가 모두 일치해야 한다.

## 금지되는 canonical source 필드

다음 값은 원천 관측에 포함하지 않는다.

- failure probability와 predicted type
- SHAP 또는 모델 contribution
- failure 예정 시각과 signal difficulty
- upstream exposure 또는 synthetic effect 크기
- scenario ID와 주입 원인

