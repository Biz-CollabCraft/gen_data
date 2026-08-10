# Canonical V3.1 Ownership and Migration Map

이 문서는 Canonical V3.1 패키지에 파일이 존재한다는 사실과 **현재 운영 소유권**을
구분한다. 저장소 책임은 PR #8에서 확정한 저장소 경계와 ontology_dashboard PR #10의
아키텍처를 따른다.

```text
gen_data
= Source Data Producer + Canonical V3.1 source/reference baseline

ontology_dashboard/systems/generator
= Semantic/ML Pipeline + versioned Model Artifact producer

ontology_dashboard/systems/backend/diagnosis
= runtime inference + Result Artifact/Evidence final producer
```

## 1. KEEP — gen_data 운영 책임

| 자산 | 현재 역할 |
|---|---|
| `canonical/dataset/*` | Canonical V3.1 source observation 및 manifest/checksum |
| `canonical/evaluation_truth/*` | source 생성 정확성·모델 평가용 격리 truth; 제품 입력 금지 |
| `scripts/generate_canonical_dataset.py` | raw/synthetic Canonical source 생성 |
| `scripts/ai4i_contract.py` | Canonical V3.1 물리/생성 기준 |
| `scripts/validate_reproducibility.py` | seed 기반 source 재현성 검증 |
| `scripts/validate_package.py`의 source gate | schema/checksum/truth isolation/topology/physics/source integrity 검증 |
| `api/replay_server.py`의 canonical replay 기능 | 저장된 source observation을 재생하는 reference/source replay |
| `api/dataset_server.py`의 canonical endpoint | source/reference fixture 확인용 read-only API |
| `experiments/connected_air_supply/*` | source-side 관계 추론 실험 및 validation fixture |
| `agent/*` | source/evidence 평가 fixture |

`evaluation_truth`와 `hidden_truth`는 KEEP이지만 공개 제품 입력이 아니라 **검증 전용**이다.

## 2. REFERENCE FIXTURE — 보존하지만 운영 SoT 아님

다음 자산은 V3.1의 호환성, 회귀, 마이그레이션 검증을 위해 그대로 보존한다.

```text
canonical/model_outputs/model_contract.json
canonical/model_outputs/model_metrics.json
canonical/model_outputs/prediction_snapshot.jsonl
canonical/model_outputs/prediction_factor.jsonl
canonical/model_outputs/prediction_timeline.jsonl
canonical/model_outputs/result_artifact.jsonl
result_artifact_sample.json
canonical/validation/* 중 model/prediction/result 검증 결과
```

이 파일의 의미는 compatibility fixture, regression fixture, migration baseline,
reference fixture regeneration 결과로 제한한다. 제품 Backend/Dashboard/Report가 이
파일을 최신 운영 prediction/result로 직접 소비하는 구조를 계약으로 삼지 않는다.

## 3. MIGRATE — ontology_dashboard가 운영 소유할 로직

현재 `model/prediction_pipeline.py`는 과거 패키지의 검증 재현성을 위해 학습과 runtime
결과 생성을 한 파일에 함께 보존한다. 이 파일 자체는 당장 삭제하지 않고
**migration source/reference implementation**으로 취급한다.

### `ontology_dashboard/systems/generator`로 이동할 책임

- `build_feature_table`: feature engineering의 운영 구현
- `fit_model`: model training
- `cross_validate`: training/evaluation pipeline
- 모델 metrics 생성
- model contract를 PR #10의 versioned Model Artifact manifest로 발전시키는 publish 로직
- 학습 모델/feature schema/version/provenance 생성

### `ontology_dashboard/systems/backend/diagnosis`로 이동할 책임

- current observation + Model Artifact 기반 runtime inference
- runtime probability/status 계산
- runtime factor/Evidence 조립
- `build_result_artifacts`에 해당하는 Product Result Artifact 생성
- Product Result Artifact provenance 생성

### reference 전용으로 gen_data에 남길 수 있는 부분

- `build_prediction_timeline` 기반 deterministic replay fixture 생성
- 과거 snapshot/factor/result fixture의 재생성 및 checksum 비교
- migration 전/후 결과 호환성 검증

`explain_latest`와 현재 `run()`은 학습과 inference를 동시에 포함하므로 장기 운영
경계에서는 그대로 이관하지 않는다. #9 integration에서 training/publish와 runtime
inference/result producer를 위 두 시스템으로 분리한다.

## 4. 실행 명령의 의미

`scripts/run_pipeline.py`의 기본 실행은 **Source Data Producer** 흐름이다.

```text
Canonical/source generation
→ source-side experiment/evaluation fixture
→ source/package validation
→ source reproducibility validation
```

`--include-reference-model-fixtures`를 명시한 경우에만 과거
`model/prediction_pipeline.py`를 실행해 model/prediction/result reference fixture를
재생성한다. 이 모드는 제품 운영 pipeline이 아니라 migration/regression 검증 모드다.

## 5. 계약 문서 Source of Truth

- Canonical source/physics/generation 계약: 이 `gen_data` 패키지
- Product architecture 및 운영 producer 책임: `Biz-CollabCraft/ontology_dashboard`
  `docs/architecture.md`
- Product Result Artifact/Evidence의 운영 계약: `ontology_dashboard`가 최종 SoT
- 이 저장소의 `RESULT_ARTIFACT_SCHEMA.md` 및 sample: V3.1 compatibility/reference fixture

동일 Product Result Artifact 계약을 두 저장소에서 독립적으로 버전 진화시키지 않는다.

## 6. 후속 #9 integration TODO

이번 PR에서는 대규모 코드 이동을 하지 않는다. 이후 #9 재배치에서 다음 순서로 처리한다.

1. `prediction_pipeline.py`의 feature/training 책임을 `systems/generator`에 맞게 재구성
2. versioned Model Artifact manifest/publish adapter 구현
3. runtime inference/result/evidence 책임을 `systems/backend/diagnosis`로 이동
4. gen_data reference fixture와 새 운영 결과 간 compatibility regression 검증
5. 제품 코드가 `gen_data/canonical/model_outputs`를 운영 결과 경로로 직접 참조하지 않는지 검사
