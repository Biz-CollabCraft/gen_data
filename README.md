# gen_data

Biz-CollabCraft 팀의 제조 예지보전 데이터 생성·예측 결과 생성·재현성 검증
저장소입니다.

## Week 2 기준 데이터

현재 팀 기준 패키지는 다음 디렉터리입니다.

- [`predictive_maintenance_canonical_v3_1/`](./predictive_maintenance_canonical_v3_1/README.md)

이 디렉터리에는 Canonical V3.1의 실제 데이터와 생성·검증 코드가 함께 있습니다.

```text
predictive_maintenance_canonical_v3_1/
├── canonical/
│   ├── dataset/             # 제품 입력이 되는 canonical observation
│   ├── evaluation_truth/    # 평가 전용 truth, 제품 UI/API 입력 금지
│   ├── model_outputs/       # prediction snapshot/factor/timeline/result artifact
│   └── validation/          # package/reproducibility 검증 결과
├── model/                   # prediction pipeline
├── scripts/                 # 생성·pipeline·release·재현성 검증
├── agent/                   # evidence/claim 평가 샘플
├── api/                     # dataset/replay server
├── experiments/             # 연결 설비 실험 자산
├── SCHEMA.md
└── RESULT_ARTIFACT_SCHEMA.md
```

원본 패키지의 `dist/*.zip`은 같은 데이터의 배포용 중복본이므로 Git 저장소에는
옮기지 않았습니다. 필요할 때 `scripts/build_release.py`로 다시 생성할 수 있습니다.

## 저장소 역할

```text
gen_data
Canonical V3.1
  ↓
prediction pipeline
  ↓
Result Artifact / Evidence
  ↓
ontology_dashboard
API / Dashboard / Report
```

제품 화면·API·리포트의 공식 Week 2 계약은
`Biz-CollabCraft/ontology_dashboard`의 `docs/mentoring-mvp-2026-08/` 문서를
기준으로 합니다. 이 저장소는 그 계약을 만족하는 데이터와 Result Artifact를
생성하는 역할을 담당합니다.

## 빠른 검증

```bash
cd predictive_maintenance_canonical_v3_1
python scripts/validate_package.py
python scripts/validate_reproducibility.py
```

동일 입력과 동일 seed에서 재현 가능한 Result Artifact를 생성하는 것이 Week 2의
핵심 완료 조건입니다.

## 데이터 사용 주의

- `canonical/dataset/`은 관측 가능한 제품 입력입니다.
- `canonical/model_outputs/`은 파생 예측 결과입니다.
- `canonical/evaluation_truth/`과 실험 hidden truth는 평가 전용이며 일반 제품
  UI/API/LLM 입력으로 사용하지 않습니다.
- `.env`, credential, cache, 가상환경과 재생성 가능한 `dist/` 압축본은 Git에
  커밋하지 않습니다.
