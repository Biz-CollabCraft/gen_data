# gen_data

Biz-CollabCraft의 제조 예지보전 **Source Data Producer** 저장소입니다.

이 저장소의 운영 책임은 raw / simulation / synthetic sensor data 생성·갱신,
Canonical V3.1 물리·생성 기준, source/reference/test fixture, seed 기반 재현성과
source baseline validation까지입니다.

## Week 2 source/reference 기준 패키지

- [`predictive_maintenance_canonical_v3_1/`](./predictive_maintenance_canonical_v3_1/README.md)

```text
predictive_maintenance_canonical_v3_1/
├── canonical/
│   ├── dataset/             # KEEP: Canonical source observation
│   ├── evaluation_truth/    # KEEP: 평가/검증 전용 truth
│   ├── model_outputs/       # REFERENCE FIXTURE: 과거 ML/prediction/result 회귀 기준
│   └── validation/          # source + reference fixture 검증 기록
├── model/                   # MIGRATION SOURCE: 과거 통합 ML/prediction 구현
├── scripts/                 # source 생성/검증 + 명시적 reference fixture 재생성
├── agent/                   # evidence/claim 평가 fixture
├── api/                     # source/reference fixture 확인용 read-only server
├── experiments/             # source-side 실험 fixture
├── OWNERSHIP_AND_MIGRATION.md
├── SCHEMA.md
└── RESULT_ARTIFACT_SCHEMA.md
```

원본 패키지의 `dist/*.zip`은 같은 데이터의 배포용 중복본이므로 Git 저장소에는
옮기지 않았습니다. 필요할 때 `scripts/build_release.py`로 다시 생성할 수 있습니다.

## 저장소 책임과 제품 흐름

PR #8의 저장소 계약과 ontology_dashboard PR #10의 내부 아키텍처에 따라 책임을
다음과 같이 고정합니다.

```text
gen_data
raw / simulation / Canonical V3.1 source data
Source Data Producer
        ↓ source/reference contract
ontology_dashboard/systems/generator
extraction → ontology mapping → topology → feature → model training
→ versioned Model Artifact
        ↓ Model Artifact contract
ontology_dashboard/systems/backend/diagnosis
current observation + Model Artifact
→ runtime inference
→ Result Artifact / Evidence
        ↓
Backend API / Frontend / Report
```

따라서 `gen_data`는 제품의 Semantic/ML pipeline, versioned Model Artifact,
runtime prediction 또는 Result Artifact/Evidence의 운영 Source of Truth가 아닙니다.

`canonical/model_outputs/*`, `result_artifact_sample.json`,
`model/prediction_pipeline.py`는 V3.1 이관 당시의 호환성·회귀 검증을 위해 남기는
**reference/regression/migration fixture**입니다. 제품 runtime은 이 파일을 최신
운영 결과로 직접 소비하지 않습니다.

자세한 KEEP / REFERENCE FIXTURE / MIGRATE 분류는
[`OWNERSHIP_AND_MIGRATION.md`](./predictive_maintenance_canonical_v3_1/OWNERSHIP_AND_MIGRATION.md)를
따릅니다.

## 빠른 source 검증

기존 기준 패키지를 변경하지 않고 검증하려면 다음을 실행합니다.

```bash
cd predictive_maintenance_canonical_v3_1
python scripts/validate_package.py
python scripts/validate_reproducibility.py
```

새 source를 생성하는 기본 orchestrator는 Canonical/source와 source-side fixture,
validation에 집중합니다.

```bash
python scripts/run_pipeline.py --days 30 --seed 42
```

기존 ML/prediction/result fixture까지 재생성해야 하는 회귀 검증에서만 명시적으로
다음 옵션을 사용합니다.

```bash
python scripts/run_pipeline.py --days 30 --seed 42 --include-reference-model-fixtures
```

## 데이터 사용 주의

- `canonical/dataset/`은 관측 가능한 source baseline입니다.
- `canonical/evaluation_truth/`과 experiment `hidden_truth/`는 평가·검증 전용이며
  제품 Dashboard/API/LLM 입력으로 노출하지 않습니다.
- `canonical/model_outputs/`은 운영 결과가 아니라 compatibility/regression fixture입니다.
- Result Artifact의 운영 producer는 `ontology_dashboard/systems/backend/diagnosis`입니다.
- `.env`, credential, cache, 가상환경과 재생성 가능한 `dist/` 압축본은 Git에
  커밋하지 않습니다.
