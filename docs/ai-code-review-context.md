# gen_data AI Code Review Contract

이 문서는 `gen_data` PR의 자동 코드 리뷰가 따라야 하는 신뢰 기준을 정의한다.
PR 자체가 이 파일을 변경하더라도 동일 PR의 승인 근거로는 **base revision의 계약**만
사용한다.

## 1. 저장소 책임

`gen_data`는 제조 예지보전 프로젝트의 **Source Data Producer**다.

```text
gen_data
raw / simulation / Canonical V3.1 source data
        ↓ source/reference contract
ontology_dashboard/systems/generator
Semantic/ML pipeline → versioned Model Artifact
        ↓
ontology_dashboard/systems/backend/diagnosis
runtime inference → Product Result Artifact / Evidence
```

따라서 `gen_data`는 운영 Model Artifact, runtime prediction, Product Result Artifact,
최종 Evidence의 운영 producer가 아니다.

## 2. Canonical Source 불변식

- `canonical/dataset/`에는 관측 가능한 source observation과 topology만 둔다.
- failure truth, model prediction, SHAP/feature contribution, synthetic effect, scenario
  정답은 Canonical source field로 유출하지 않는다.
- `canonical/evaluation_truth/`와 experiment `hidden_truth/`는 평가·검증 전용이며
  Dataset API, 제품 Dashboard/API/LLM 입력으로 노출하지 않는다.
- `SUPPLIES_AIR_TO`는 topology이며 인과 정답으로 취급하지 않는다.
- source-side experiment와 daemon은 committed Canonical baseline을 임의로 mutate하지
  않는다.

## 3. 생성·재현성 계약

- 동일 입력, 동일 seed, 동일 generation contract는 동일 결과를 재현해야 한다.
- 다른 seed는 적어도 하나 이상의 stochastic source output을 변경해야 한다.
- `dataset_manifest.json`의 checksum과 ownership metadata는 실제 committed output과
  일치해야 한다.
- 물리 규칙, topology, observation cardinality, maintenance/tool-wear continuity는
  `scripts/validate_package.py`가 검증하는 release gate를 깨면 안 된다.
- 재현성 검증 결과를 단순 문서 주장으로 PASS 처리하지 않는다. 실행 결과가 있어야 한다.

## 4. Reference / Migration Fixture 계약

다음 자산은 보존할 수 있지만 운영 SoT로 해석하지 않는다.

- `canonical/model_outputs/*`
- `result_artifact_sample.json`
- `model/prediction_pipeline.py`
- model/prediction/result 관련 validation output

이 자산은 compatibility/reference/regression/migration fixture다. 제품 runtime이 이를
최신 운영 결과처럼 직접 소비하도록 계약을 바꾸면 안 된다.

## 5. 실시간 daemon 계약

- `physics_engine.py`는 repository root의 Canonical V3.1 generator를 compatibility
  facade로 재사용한다.
- `GEN_DATA_CANONICAL_ROOT`는 외부 baseline 비교가 필요할 때만 override한다.
- daemon의 `.raw` / protocol envelope / 내부 decode preview는 Source Data Producer
  책임 범위에 머문다.
- daemon output에 failure truth, hidden truth, evaluation labels를 섞지 않는다.
- `ontology_dashboard/data/sensor`, feature, model, result 저장 경로를 gen_data가 직접
  소유하거나 쓰지 않는다.

### Runtime Overlay 불변식

- Closed-loop feedback은 전체 Generator/Canonical을 다시 만들지 않고 **정비 대상 설비만**
  opt-in Overlay로 분기한다.
- `maintenance.started` 이후 대상 설비 Canonical/live Observation은 중단하지만 다른 설비
  global clock과 생성은 계속된다.
- maintenance effect는 복제된 Overlay Snapshot에만 적용하고 committed Canonical source나
  기존 Runtime object를 mutate하지 않는다.
- MVP `TOOL_REPLACEMENT`는 `tool_wear_min reset -> 0 min` whitelist를 벗어나면 fail-fast한다.
- branch-local Fast-forward는 source runtime virtual time catch-up 목적이며 global clock을
  이동시키지 않는다.
- Overlay Observation은 append-only이며 `source_kind=maintenance_replay_overlay`, session,
  branch, maintenance, history segment lineage를 보존한다.
- `gen_data`는 Model Artifact/`history_requirement`을 읽거나 inference-ready를 판정하지 않는다.
  output event는 `runtime_overlay.observations.available` 의미만 가져야 한다.
- Prediction, Product Result/Evidence, `warming_up/history_insufficient/ready` 판정은 Backend
  Diagnosis 소유권이다.

## 6. Release 계약

- 저장소는 평탄화되어 있지만 release artifact 이름과 ZIP 내부 root는
  `predictive_maintenance_canonical_v3_1`을 유지한다.
- release ZIP은 Canonical/reference package에 필요한 파일만 포함하고 `.github/`,
  daemon prototype 문서/런타임 output, credentials/cache를 섞지 않는다.
- release build는 실제 압축 해제 후 package validation을 다시 통과해야 한다.

## 7. CI / Review 판정 기준

PR의 선행 `source-validation`은 최소한 다음을 검증한다.

- Canonical/source + reference fixture package validation
- full seed reproducibility validation
- evaluation-truth API isolation
- Canonical generator + daemon/protocol import smoke
- release ZIP build/extract/layout validation
- Python compile
- validation baseline drift
- whitespace consistency

자동 리뷰는 CI PASS를 correctness의 절대 증명으로 취급하지 않는다. 다만 위 실행
증거가 없는 상태에서 해당 항목을 PASS로 단정해서도 안 된다.

`source-validation`이 실패하면 Merge Readiness는 반드시 **Not Ready**다. 실패 로그의
구체적인 step/error를 근거로 원인과 수정 방향을 제시한다.

## 8. 우선 탐지할 결함

1. Canonical source에 truth/model/result field가 유출되는 변경
2. seed 재현성 또는 manifest/checksum을 깨는 변경
3. AI4I physics/topology/maintenance continuity를 깨는 생성 로직
4. Dataset API 또는 daemon을 통한 evaluation/hidden truth 노출
5. `gen_data`가 운영 Model/Result/Evidence producer 책임을 가져가는 변경
6. reference fixture를 운영 결과처럼 사용하는 변경
7. repository flattening 이후 잘못된 상대 경로/root 계산
8. release ZIP 이름·내부 root·포함 파일 계약을 깨는 변경
9. workflow가 실제 검증을 실행하지 않는데 PASS evidence로 주장하는 변경
10. secrets/OIDC 권한을 과도하게 넓히거나 fork PR에 privileged identity를 노출하는 변경
11. Runtime Overlay가 비대상 설비/global clock/Canonical source를 함께 변경하는 수정
12. `gen_data`가 Overlay readiness를 Model Artifact/history requirement로 판단하는 수정
