# ADR: Canonical Dataset, Agent Evaluation Scenario, Replay Runtime 분리

> **현재 책임 해석:** 이 ADR의 Canonical/source·truth·experiment 분리 결정은
> `gen_data`의 운영 계약으로 유지한다. 아래 model output/replay prediction 항목은
> V3.1 reference fixture 정책이며, 운영 ML/Result 책임은 `OWNERSHIP_AND_MIGRATION.md`와
> `ontology_dashboard/docs/architecture.md`의 최신 경계를 따른다.

## 결정

압축기와 CNC는 독립 관측 데이터로 생성한다. `SUPPLIES_AIR_TO`는 설비 구성 관계로만 canonical dataset에 포함한다. 압축기 때문에 CNC 센서가 얼마나 바뀌었다는 값은 canonical dataset에 기록하지 않는다.

여기서 "압축기와 CNC의 독립"은 두 설비군 사이에 synthetic causal effect를
넣지 않는다는 뜻이다. CNC 내부 센서들은 독립 생성하지 않는다. Air/process와
torque/RPM은 AI4I 방식의 결합 물리 관계를 사용한다.

관계 추론 기능을 시험해야 할 때만 `experiments/`에 별도 관측 세트를 만든다. 실험 관측 파일은 canonical sensor schema를 그대로 사용하며 `exposure`, `delta`, `cause`, `scenario` 컬럼을 추가하지 않는다. 생성 시 사용한 원인·대상·기간·효과 크기는 평가기 전용 `hidden_truth/`에만 둔다.

## 데이터 계층

```text
Canonical source
  asset_master + asset_relation
  compressor observations
  CNC observations + production + maintenance

Evaluation truth
  failure schedule
  compressor/CNC failure truth

Derived model output (reference/regression fixture)
  prediction snapshot
  model factor
  prediction timeline
  result artifact

Optional agent experiment
  public observations with the same source schema
  hidden injected-cause truth
```

## 모델 정책

- 압축기 모델은 압축기 센서만 사용한다.
- 현재 sanity benchmark의 CNC 모델은 CNC 센서만 사용한다. 생산 이력 feature는 향후 별도 as-of join 검증 후 추가할 수 있다.
- `asset_relation.csv`는 모델의 기본 입력이 아니다.
- 상류 관계 feature는 canonical model에 자동 포함하지 않는다.
- 모델 출력은 원천 CSV에 역기입하지 않는다.
- Reference replay용 예측은 시간별 `prediction_timeline.jsonl`로 사전 계산하며 canonical source와 분리한다.
- `result_artifact.jsonl`은 V3.1 compatibility fixture로 보존한다. 운영 제품은 Backend가 생성한 Result Artifact/Evidence를 소비한다.

## AI4I 물리 정책

- Process temperature는 air temperature에서 파생한다.
- RPM은 torque와 목표 동력으로부터 역산한 값에 residual을 더한다.
- 정상 RPM은 inverse 관계를 100% 적용하지 않고 AI4I 유사 분산을 유지하기 위해
  baseline 대비 ideal RPM 편차의 30%를 반영한다.
- PWF low-power branch는 3,200W 목표를 지원 RPM 범위에서 만족시키기 위해
  torque를 먼저 34Nm 방향으로 조정한 뒤 RPM을 전력식으로 역산한다.
- 자산별 개체차는 전체 AI4I 분산을 압도하지 않는 작은 offset으로 제한한다.
- PWF, HDF, OSF, TWF truth는 고장 시각 센서값이 정의 조건을 만족해야 한다.
- `validate_package.py`가 상관, 분산, ordering, failure condition을 release gate로 검사한다.
- 공구 교체 reset은 `maintenance_event.started_at`과 같은 tick에서만 허용하고,
  해당 CNC 행은 `operating_state=maintenance`여야 한다.
- running→running 구간에서 1분을 초과하는 tool wear 감소를 금지한다.

## Replay 정책

- Replay Server는 canonical CSV에 없는 센서값을 생성하지 않는다.
- simulation clock만 진행하며 현재 시점의 CSV row를 공개한다.
- reference replay seek 시 모델을 재학습하지 않고 해당 시점 이전의 가장 가까운 사전 계산 prediction fixture를 사용한다.
- start, pause, resume, reset, speed, seek를 지원한다.
- 실시간 갱신은 SSE를 기본 transport로 사용한다.
- evaluation truth와 experiment hidden truth는 Replay API로 노출하지 않는다.
- 정비 중 행과 데이터 종료 직전 prediction horizon은 학습·평가에서 제외한다.
- 모델 계약은 dataset manifest 및 입력·출력 checksum과 결합한다.

### Closed-loop Runtime Overlay 예외 경로

위 Canonical Replay 정책은 계속 read-only 기준이다. 정비 결과를 시연에 반영해야 할
때는 Canonical Replay 자체를 변경하지 않고 별도의 opt-in Runtime Overlay를 사용한다.

- `maintenance.started` 이후 대상 설비의 Canonical/live Observation만 중단한다.
- 다른 설비는 기존 global Replay clock을 계속 따른다.
- 정비 완료 `state_patch`는 Canonical Runtime/CSV가 아니라 복제된 Overlay Snapshot에만
  적용한다.
- `TOOL_REPLACEMENT`의 MVP patch는 `tool_wear_min reset -> 0 min`만 허용한다.
- `maintenance.replay_requested` 이후 대상 설비 branch clock만 현재 source-runtime
  virtual time까지 sleep 없이 catch-up한다.
- catch-up 이후에도 해당 설비는 Overlay branch에서 정상 tick cadence를 이어간다.
- Overlay Observation은 `source_kind=maintenance_replay_overlay`, maintenance/branch
  lineage를 포함한 append-only 별도 저장 경로에 쓴다.
- `gen_data`는 Model Artifact 또는 `history_requirement`을 소비하지 않는다. 새 Observation
  배치가 Backend에서 소비 가능하다는 `runtime_overlay.observations.available`만 알린다.
- inference-ready 판정, `warming_up/history_insufficient`, Prediction 및 Product
  Result/Evidence 생성은 Backend Diagnosis가 소유한다.

## 에이전트 정책

에이전트는 센서 변화, 시간적 선후관계, 자산 관계, 정비 이력을 조합해 원인 **후보**를 제시한다. `hidden_truth/`는 에이전트에 제공하지 않는다. 평가기는 후보 자산, relation traversal, 증거 범위, 인과 표현의 신중함을 채점한다. Sensor evidence와 maintenance evidence를 구분하며, 정비 근거는 canonical maintenance row와 정확히 일치해야 한다.

Optional experiment는 positive upstream-relation 16건과 negative local-only 4건을 포함한다. Negative case에서는 upstream compressor observation이 canonical 값과 동일해야 하며, 에이전트가 `NO_UPSTREAM_RELATION`과 `unlikely`를 선택해야 한다.

Smoke example case는 정답 예시를 포함하므로 formal benchmark 집계에서 제외한다.

## 금지 사항

- canonical CNC observation에 `upstream_pressure_deficit` 추가
- `simulated_exposure_index`, `torque_delta_nm`, `wear_multiplier` 추가
- 생성기 내부 failure schedule을 feature로 사용
- agent 결과를 hidden truth와 사전 join
- synthetic scenario를 실제 산업 인과관계로 표현
- Binary 위험 모델의 `predicted_failure_type`을 multiclass failure-mode 예측으로 표현

