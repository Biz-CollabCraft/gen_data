# V3.1 구현 결과

> 이 문서는 V3.1 구현 당시 기록이다. model/prediction/Result Artifact 관련 구현은
> 현재 migration/reference baseline으로 보존하며, 운영 소유권은
> `OWNERSHIP_AND_MIGRATION.md`를 따른다.

## 목적

V2의 데이터 계층 분리와 Replay 기능은 유지하면서, CNC 생성기를 AI4I 2020의
핵심 물리 관계와 failure condition에 맞게 수정하고 agent benchmark와 Result
Artifact를 보강했다.

V3.1에서는 공구 교체와 센서 상태 전이를 다시 정렬했다. Tool wear reset은
정비 시작 tick에서만 적용하며, 같은 행은 `operating_state=maintenance`로
기록한다.

## 구현 내용

### AI4I 물리 생성

- Air temperature를 먼저 생성
- Process temperature를 air + gap + residual로 파생
- Torque를 먼저 생성
- 목표 동력과 torque로 ideal RPM을 계산하고 baseline 대비 편차의 30%와
  residual을 반영
- CNC 자산 offset을 ±4% 방식에서 작은 절대 offset으로 축소

### Failure condition

- PWF low/high power branch
- HDF temperature-gap 및 low-RPM 조건
- OSF 제품 유형별 overstrain threshold
- TWF 200~240분 tool-wear 구간
- RNF condition-independent event

### Validation gate

`package_validation.json`에 다음을 추가했다.

- `ai4i_physics.air_process_correlation`
- `ai4i_physics.rpm_torque_correlation`
- `ai4i_physics.process_temperature_ordering`
- `ai4i_physics.sensor_distribution`
- `ai4i_physics.failure_mode_conditions`
- failure timestamp별 상세 조건 값
- `tool_wear_continuity.running_reset_count`
- tool replacement event와 reset timestamp 1:1 정렬

### Agent negative controls

- Positive upstream case: 16
- Negative local-only case: 4
- `candidate_upstream_asset_id=null`
- `relation_type=NO_UPSTREAM_RELATION`
- `claim_status=unlikely`
- Negative rejection accuracy와 false upstream claim rate 추가
- Sensor/maintenance evidence type 분기와 canonical maintenance 근거 검증

### Result Artifact reference fixture

- `canonical/model_outputs/result_artifact.jsonl`
- `SCHEMA.md`
- `RESULT_ARTIFACT_SCHEMA.md`
- `result_artifact_sample.json`

## 최종 데이터 결과

| 항목 | 결과 |
|---|---:|
| 압축기 관측 | 123,840 |
| CNC 관측 | 495,360 |
| 생산 cycle | 244,929 |
| 정비 event | 1,151 |
| 압축기 failure | 20 |
| CNC failure | 56 |
| Public agent case | 20 |
| Prediction timeline | 68,208 |
| Result Artifact reference fixture | 100 |

## 물리 검증

| 항목 | V2 | V3.1 |
|---|---:|---:|
| corr(air, process) | -0.086 | 0.919768 |
| corr(rpm, torque) | -0.001 | -0.845823 |
| process < air | 66,509 | 0 |
| air σ | 6.99 | 1.953310 |
| process σ | 6.74 | 1.512621 |
| RPM σ | 135.45 | 185.895344 |
| torque σ | 6.07 | 10.563547 |

Failure condition은 PWF 14/14, HDF 21/21, OSF 11/11, TWF 6/6,
RNF 4/4를 통과했다.

## 모델 결과

| 대상 | ROC-AUC | PR-AUC | Top 5% recall |
|---|---:|---:|---:|
| 압축기 | 0.734353 | 0.222111 | 0.283333 |
| CNC | 0.813453 | 0.529580 | 0.598323 |

V3.1 CNC 물리 precursor가 반영되면서 binary sanity benchmark의 분리 가능성이
상승했다. 실제 운영 성능으로 해석하지 않는다.

## 명시적 한계

- Result Artifact의 predicted type은 아직 binary generic class다.
- Failure condition은 합성 생성 계약이며 실제 산업 인과 증거가 아니다.
- Agent benchmark는 local-only negative를 포함하지만 pure-normal negative와
  confounding case는 아직 없다.
- Replay는 사전 계산 timeline을 사용하며 실시간 model artifact 추론이 아니다.

