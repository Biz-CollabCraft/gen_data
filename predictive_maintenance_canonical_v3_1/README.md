# Predictive Maintenance Canonical V3.1

AI4I 2020의 핵심 물리 관계를 반영한 압축기·CNC 합성 데이터셋, 시간별
예측 결과, positive/negative 에이전트 평가 자산, CSV Replay Server를 함께
제공한다.

신규 제품 연동과 팀 공유의 기준 경로는
`predictive_maintenance_canonical_v3.1/`이다. 기존 이름이 V3인 작업 폴더를
V3.0 기준본으로 간주하거나 신규 ingestion 입력으로 사용하지 않는다.

```text
AI4I-style coupled CNC physics
→ canonical source와 evaluation truth 분리
→ leave-one-site-out prediction timeline
→ 공통 Result Artifact
→ Replay Server와 SSE
```

## V3.1에서 해결한 문제

- Air/process 온도를 독립 생성하지 않고 결합 물리식으로 생성
- Torque를 먼저 생성하고 power 관계로 RPM을 파생
- AI4I 유사 센서 분산으로 자산 편차와 시계열 잡음 재조정
- PWF, HDF, OSF, TWF가 고장 시각에 실제 센서 조건을 만족
- `validate_package.py`에 `ai4i_physics` 검증 gate 추가
- 상류 원인이 없는 `negative_local_only` case 4건 추가
- `NO_UPSTREAM_RELATION`과 `claim_status=unlikely` 채점 지원
- 대시보드·에이전트·보고서 공통 `result_artifact.jsonl` 추가
- 공구 마모 초기화를 실제 정비 시작 tick으로 이동
- 가동 중 tool wear 감소와 정비-event/reset 정렬을 release gate로 검증
- Agent evidence에 sensor와 maintenance 이력을 함께 표현·검증

## 핵심 데이터 원칙

- Canonical source에는 관측 가능한 센서·생산·정비·설비 관계만 둔다.
- Failure truth, 모델 결과, synthetic effect, scenario 정답을 source에 넣지 않는다.
- `SUPPLIES_AIR_TO`는 topology이며 인과 정답이 아니다.
- Optional experiment는 canonical CSV를 수정하지 않는다.
- Replay Server는 센서를 다시 생성하지 않고 canonical CSV를 시간순으로 공개한다.

## AI4I 물리 계약

V3.1 CNC 생성기는 다음 관계를 보존한다.

```text
process_temperature ≈ baseline_process + 0.68 × air_deviation + residual
ideal_rpm = power_target × 60 / (2π × torque)
rpm ≈ baseline_rpm + 0.30 × (ideal_rpm - baseline_rpm) + residual
power = torque × rpm × 2π / 60
```

Failure condition:

```text
PWF: power < 3500W or power > 9000W
HDF: process - air < 8.6K and rpm < 1380
OSF: tool_wear × torque > L 11000 / M 12000 / H 13000
TWF: tool_wear between 200 and 240 minutes
RNF: condition-independent random failure
```

30일 seed 42 검증 결과:

| 항목 | 결과 |
|---|---:|
| corr(air, process) | 0.919768 |
| corr(rpm, torque) | -0.845823 |
| process < air | 0행 |
| air temperature σ | 1.953310 |
| process temperature σ | 1.512621 |
| RPM σ | 185.895344 |
| torque σ | 10.563547 |

모든 CNC failure truth가 해당 조건을 통과했다.

```text
PWF 14/14
HDF 21/21
OSF 11/11
TWF  6/6
RNF  4/4
```

Tool wear continuity:

```text
running → running reset                 0
tool replacement event                731
maintenance start와 정렬된 reset      731
정비 이력 없이 발생한 reset             0
reset 없이 끝난 tool replacement        0
```

## 폴더 구조

```text
predictive_maintenance_canonical_v3.1/
├── canonical/
│   ├── dataset/
│   ├── evaluation_truth/
│   ├── model_outputs/
│   └── validation/
├── experiments/connected_air_supply/
│   ├── public_cases/
│   ├── public_case_index.csv
│   ├── hidden_truth/
│   └── experiment_manifest.json
├── model/prediction_pipeline.py
├── agent/
├── api/
├── scripts/
├── dashboard/
├── SCHEMA.md
├── RESULT_ARTIFACT_SCHEMA.md
├── V3_1_CHANGELOG.md
├── V3_1_IMPLEMENTATION_REPORT.md
├── V3_1_RELEASE_VERIFICATION.md
├── FINAL_AUDIT_REPORT.md
└── result_artifact_sample.json
```

## 설치

Python 3.11 이상을 권장한다.

```bash
cd predictive_maintenance_canonical_v3.1
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
```

SHAP은 선택 사항이다. 미설치 시 표준화된 linear-logit contribution을 사용한다.

```bash
.venv/bin/pip install -r requirements-optional.txt
```

## 전체 재생성

```bash
.venv/bin/python scripts/run_pipeline.py \
  --days 30 \
  --seed 42 \
  --rate-profile balanced_demo \
  --interventions 4 \
  --negative-cases 4
```

생성 순서:

1. Canonical dataset과 evaluation truth
2. Positive upstream case 16건과 negative local-only case 4건
3. Positive/negative evaluator smoke fixture
4. 구조·checksum·AI4I physics validation
5. 모델, prediction timeline, Result Artifact
6. 동일 seed 재현성 검증

## 생성 결과

| 항목 | 결과 |
|---|---:|
| 자산 | 100 |
| 관계 | 80 |
| 압축기 관측 | 86,400 |
| CNC 관측 | 345,600 |
| 생산 cycle | 170,875 |
| 정비 event | 790 |
| 전체 failure truth | 76 |
| Agent public case | 20 |
| Prediction timeline | 68,208 |
| Result Artifact | 100 |

모델 sanity benchmark:

| 대상 | ROC-AUC | PR-AUC | Top 5% recall |
|---|---:|---:|---:|
| 압축기 | 0.734353 | 0.222111 | 0.283333 |
| CNC | 0.813453 | 0.529580 | 0.598323 |

이는 실제 운영 성능 보장이 아니라 합성 데이터의 시간 예측 가능성을 확인하는
sanity benchmark다.

## Result Artifact

공통 결과는 다음 파일에 있다.

```text
canonical/model_outputs/result_artifact.jsonl
```

핵심 필드:

```text
asset_id
failure_probability
predicted_failure_type
status_grade
top_factors
recommended_action
provenance
```

현재 모델은 binary failure-within-24h 모델이므로 `predicted_failure_type`은
PWF/HDF/OSF/TWF multiclass 결과가 아니다. 자세한 계약은
`RESULT_ARTIFACT_SCHEMA.md`를 따른다.

## Dataset API

```bash
.venv/bin/python api/dataset_server.py --port 8000
```

주요 endpoint:

```text
GET /manifest
GET /assets
GET /relations
GET /observations/compressors
GET /observations/cnc
GET /production
GET /maintenance
GET /predictions
GET /prediction-factors
GET /prediction-timeline
GET /result-artifacts
GET /experiments
```

기본 설정에서는 evaluation truth와 experiment hidden truth를 노출하지 않는다.

## Time Machine Replay Server

```bash
.venv/bin/python api/replay_server.py --port 8001 --speed 60
```

```text
GET  /simulation/status
GET  /simulation/snapshot
GET  /simulation/history
GET  /simulation/events

POST /simulation/start
POST /simulation/pause
POST /simulation/resume
POST /simulation/reset
POST /simulation/speed?x=60
POST /simulation/seek?time=2026-08-12T15:00:00+09:00
```

`/simulation/events`는 `text/event-stream` SSE를 사용한다.

## Agent benchmark

Case 구성:

```text
positive_upstream_relation  16
negative_local_only          4
```

Negative 정답 계약:

```json
{
  "candidate_upstream_asset_id": null,
  "relation_type": "NO_UPSTREAM_RELATION",
  "claim_status": "unlikely"
}
```

평가 지표:

- Positive upstream accuracy
- Negative rejection accuracy
- False upstream claim rate
- Relation accuracy
- Temporal evidence rate
- Causal-language calibration
- Canonical maintenance evidence accuracy

`evidence_observations[]`는 `evidence_type`으로 구분한다.

```text
sensor
→ asset_id, sensor, direction, started_at, ended_at

maintenance
→ asset_id, maintenance_id, maintenance_type,
  started_at, completed_at, tool_replaced
```

Maintenance evidence는 `canonical/dataset/maintenance_event.csv`의 동일 ID와
자산·유형·시간·공구 교체 여부가 모두 일치해야 유효하다.

Smoke example은 positive 1건과 negative 1건이며 formal benchmark에서는 제외한다.

```bash
.venv/bin/python agent/evaluate_agent_claims.py \
  agent/agent_claims.example.jsonl
```

## 검증

```bash
.venv/bin/python scripts/validate_package.py
```

`canonical/validation/package_validation.json`의 `ai4i_physics`에서 상관,
분산, 온도 ordering, failure mode 조건과 `tool_wear_continuity`를 확인할 수 있다.

Canonical-only 재현성:

```bash
.venv/bin/python scripts/validate_reproducibility.py \
  --scope canonical --days 2
```

전체 재현성:

```bash
.venv/bin/python scripts/validate_reproducibility.py \
  --scope full --days 5
```

`--scope full --days 4` 이하는 명시적인 최소 기간 오류를 반환한다.

## 배포 ZIP

```bash
.venv/bin/python scripts/build_release.py
```

```text
dist/predictive_maintenance_canonical_v3.1.zip
dist/predictive_maintenance_canonical_v3.1.zip.sha256
```

배포 스크립트는 macOS metadata·venv·cache를 제외하고, ZIP CRC 검사와 실제
압축 해제 후 package validation까지 수행한다.

## 표현 원칙

이 패키지는 실제 설비와 양방향 동기화되는 완전한 디지털 트윈이 아니다.

권장 표현:

> AI4I 물리 계약과 canonical replay를 갖춘 합성 예지보전 Time Machine

