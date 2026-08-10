# Result Artifact Schema

> **현재 소유권:** 이 문서와 `canonical/model_outputs/result_artifact.jsonl`은
> Canonical V3.1의 **compatibility/reference fixture**다. 제품 운영 Result Artifact의
> canonical Source of Truth와 최종 producer는 `Biz-CollabCraft/ontology_dashboard`의
> `systems/backend/diagnosis`다. 동일 계약을 두 저장소에서 독립적으로 버전 진화시키지
> 않는다.

`canonical/model_outputs/result_artifact.jsonl`은 V3.1 이관 당시 대시보드, 에이전트,
리포트가 모델 내부 파일을 직접 소비하지 않도록 정의했던 공통 결과 fixture다.

## 계약

- 형식: UTF-8 JSON Lines
- schema version: `result-artifact-v1.0`
- 한 행: 자산 한 대의 최신 예측 결과
- source type: `derived_result_artifact`
- canonical source mutation: 항상 `false`

## 필드

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `artifact_id` | string | Y | 결과 고유 ID |
| `artifact_type` | string | Y | `predictive_maintenance_result` |
| `schema_version` | string | Y | `result-artifact-v1.0` |
| `asset_id` | string | Y | 대상 자산 |
| `asset_type` | enum | Y | `compressor`, `cnc` |
| `observed_at` | ISO-8601 string | Y | 예측 기준 시각 |
| `prediction_horizon_hours` | integer | Y | 예측 시간 범위 |
| `prediction_task` | string | Y | 현재 `binary_failure_within_horizon` |
| `failure_probability` | number | Y | 0~1 위험도 |
| `predicted_failure_type` | string | Y | 현재 binary 모델의 일반 위험 class |
| `status_grade` | enum | Y | `normal`, `attention`, `warning`, `critical` |
| `confidence` | number | Y | 0~1, 확률의 결정 경계 거리 기반 값 |
| `top_factors` | array | Y | Top-3 feature contribution |
| `recommended_action` | object | Y | 행동과 우선순위 |
| `provenance` | object | Y | dataset/model/result 출처 |

## `top_factors[]`

| 필드 | 타입 | 설명 |
|---|---|---|
| `rank` | integer | 1~3 |
| `feature` | string | 파생 feature 이름 |
| `feature_value` | number | 자산 내부 정규화 feature 값 |
| `signed_contribution` | number | 모델 logit에 대한 부호 있는 기여 |
| `direction` | enum | `risk_up`, `risk_down` |
| `explanation_method` | string | SHAP 또는 linear-logit contribution |

## `recommended_action`

| 상태 | 행동 | 우선순위 |
|---|---|---|
| `critical` | `immediate_inspection_and_stop_review` | `urgent` |
| `warning` | `inspect_within_current_shift` | `high` |
| `attention` | `schedule_targeted_diagnostic_check` | `medium` |
| `normal` | `continue_monitoring` | `routine` |

추천 행동은 정책 기반 파생값이며 자동 설비 정지 명령이 아니다.

## Failure type 의미

현재 모델은 **향후 24시간 내 고장 여부를 예측하는 binary 모델**이다. 따라서
`predicted_failure_type`은 `failure_risk` 또는 `no_significant_risk`이며, PWF,
HDF, OSF, TWF를 분류하는 multiclass 결과로 해석하면 안 된다. Multiclass 모델을
추가하더라도 동일 필드 계약을 유지하고 model contract의 task를 갱신한다.

## 소비 원칙

- 이 저장소에서는 schema/sample/regression compatibility 검증에 사용한다.
- 제품 대시보드·에이전트·보고서는 운영 Backend API가 제공하는 Result Artifact/Evidence를 소비한다.
- 에이전트는 artifact만으로 원인을 확정하지 않고 canonical evidence를 추가 조회한다.
- 보고서는 provenance를 함께 보존한다.
- canonical sensor CSV와 result artifact를 하나의 원천 테이블로 합치지 않는다.

