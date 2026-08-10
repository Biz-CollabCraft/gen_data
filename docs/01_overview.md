# gen_data — 01. 개요

## 정의

`gen_data`는 Canonical V3.1의 물리 계산 로직(AI4I 물리 계약: air/process 온도 결합, torque/rpm 역산, PWF/HDF/OSF/TWF/RNF 고장 조건)을 **재사용**하여, 압축기·CNC 자산의 센서 데이터를 **실시간으로, 산업용 통신 프로토콜(Modbus TCP 등) 캡처 형태로, 라인 단위 디렉터리 구조로** 계속 생성해내는 데몬이다. 팀 저장소에서 Canonical 기준본의 실제 경로는 `predictive_maintenance_canonical_v3_1/`이다.

## 저장소 구조

`gen_data`와 `ontology_dashboard`는 **GitHub Organization `Biz-CollabCraft` 안에 존재하는 서로 다른 두 개의 repository**이며, 로컬에서는 `C:\kosa\project\final\` 하위에 나란히 위치하는 두 워크스페이스로 동기화된다. 하나의 repo 안에서 브랜치로 나누는 방식이 아니라, **repo 자체를 분리**하고 그 사이를 파일시스템(공유 데이터 경로)으로만 연결하는 구조다.

```
Biz-CollabCraft (GitHub Organization)
├── gen_data                (repo 1 — 데이터 "생성" 담당)
│   물리 계산 → 실시간 프로토콜 캡처 → 파일 저장
│
└── ontology_dashboard      (repo 2 — 데이터 "가공·사용" 담당)
    Extraction Agent → Ontology Mapping Agent → Topology Agent
    → Feature Builder → Model Registry → Dashboard

로컬 워크스페이스 (C:\kosa\project\final\)
├── gen_data\                (repo 1의 로컬 clone)
└── ontology_dashboard\      (repo 2의 로컬 clone)
    두 디렉터리는 나란히 위치하며, 코드로 직접 연동하지 않고
    공유 데이터 경로(파일시스템)로만 연결된다.
```

이 전제를 두는 이유는 기획서(§1)의 상위 목표 — "서로 다른 제조 환경의 원본 데이터를 Agent가 자동으로 해석"하는 플랫폼 — 를 실제로 검증하려면, `ontology_dashboard`가 `gen_data`의 내부 구현(브랜치 히스토리, 커밋)을 몰라도 **오직 파일 경로 계약만으로** 데이터를 읽어낼 수 있어야 하기 때문이다. 두 repo가 물리적으로 분리되어 있으면 이 "내부를 몰라도 된다"는 조건이 코드 구조로도 강제된다 — 같은 repo의 다른 브랜치였다면 실수로 서로의 내부 모듈을 import하는 결합이 생기기 쉽지만, 별도 repo면 그 결합 자체가 애초에 불가능하다.

`ontology_dashboard`의 Extraction Agent·Ontology Mapping Agent·Topology Construction Agent는 **"읽을 파일이 실제로 존재하고, 계속 갱신되는 상황"**을 전제로 설계되어 있다. `gen_data`는 그 전제를 만족시키는 **데이터 생성 담당**이고, `ontology_dashboard`는 그 데이터를 **가공해서 사용하는 담당**이다 — 두 repo의 관계는 "생성 → 가공 → 사용"의 단방향 파이프라인으로 정리된다.

```
[생성]  gen_data (repo 1)            [가공 → 사용]  ontology_dashboard (repo 2)
──────────────────                   ─────────────────────────────────────
Canonical V3.1 물리 함수 재사용            가공: Extraction Agent
→ 실시간 .raw 캡처 생성                     → Ontology Mapping Agent
→ 라인별 병렬 저장          ──파일시스템──▶      → Topology Construction Agent
                                              → Feature Builder (.npy)
                            (오직 이 경로로만 연결,                → Model Training
                             repo 간 코드 import 없음,                → Versioned Model Artifact
                             augmenter 등 중간 가공 모듈 없음)          (systems/generator 책임, 여기까지)
                                        사용: Runtime Inference
                                              → Product Result Artifact / Evidence
                                              (systems/backend/diagnosis 책임)
                                              → Dashboard (시각화)
```

`systems/generator`는 Model Artifact(학습된 모델)를 만드는 것까지만 담당하며, 그 모델로 실시간 추론을 수행해 실제 서비스가 쓰는 Result Artifact/Evidence를 만드는 것은 `systems/backend/diagnosis`의 책임이다. 이 두 producer를 하나로 뭉뚱그려 표현하지 않는다.

gen_data는 데이터를 **만드는 쪽**, ontology_dashboard는 그 데이터를 **읽어서 의미를 해석하고(가공) 예측·시각화에 쓰는 쪽(사용)**으로 역할이 명확히 나뉜다. 화살표는 한쪽 방향(gen_data → ontology_dashboard)으로만 흐르며, ontology_dashboard가 gen_data로 값을 되돌려 쓰거나 gen_data의 동작에 개입하는 경로는 없다. 초기 검토 단계에 있었던 별도 증강(augmentation) 모듈은 최종 설계에서 제외되었으며, gen_data가 만든 데이터를 ontology_dashboard가 직접 읽어 가공하는 2단 구조로 확정한다.

두 repo는 코드로 직접 연동하지 않고 **파일시스템을 통해서만** 연결된다. `gen_data`가 `GEN_DATA_OUTPUT_DIR`(§03 상세 스펙 §1 참조)에 파일을 쌓고, `ontology_dashboard`가 같은 경로를 `data_dir`로 바라보면 된다. 구체적인 경로 계약(`data/sensor`, `data/result` 등)은 §데이터 경로 계약(아래) 참조.

## 데이터 경로 계약 — gen_data → ontology_dashboard

`ontology_dashboard`가 `gen_data`의 `.raw` 파일 스트림을 어떻게 읽어 어디에 쓰는지는 다음과 같이 확정한다.

```
gen_data 쪽 (쓰기)                          ontology_dashboard 쪽 (읽기 → 변환 → 쓰기)
─────────────────                          ──────────────────────────────────────
GEN_DATA_OUTPUT_DIR/raw/                     Extraction Agent가 .raw 스트림을 읽음
  fac{site}/line{cell}/{date}/{time}.raw          ↓ (프로토콜 디코딩 + 재구성)
                                              ontology_dashboard/data/sensor/
                                                (재구성된 센서 로그, 사람이 읽을 수 있는 형태)
                                                    ↓ (Ontology/Topology Agent, Feature Builder)
                                              ontology_dashboard/data/result/*.npy
                                                (Feature, 모델 학습·예측 입력)
```

`gen_data`는 `ontology_dashboard/data/sensor`·`ontology_dashboard/data/result` 경로를 알지도, 쓰지도 않는다 — 이 경로들은 전적으로 `ontology_dashboard` 쪽 책임이다. 현재 `gen_data` 구현은 `GEN_DATA_OUTPUT_DIR/raw/`에 캡처를 저장하고, 디코딩 smoke/관찰용 파생 로그를 `GEN_DATA_OUTPUT_DIR/sensor/`에도 기록한다. 이 파생 로그는 `ontology_dashboard/data/sensor/`와는 별도 경로이며 제품 입력 계약을 대신하지 않는다.

> **참고 — 기존 v3.1 릴리스 출처와 팀 기준 경로의 구분**: 과거 개인 저장소의 배포본 이름에는 `predictive_maintenance_canonical_v3.1` 표기가 사용되었다. 현재 팀 저장소에서 이관되는 실제 filesystem 기준 경로는 `predictive_maintenance_canonical_v3_1/`이다. 버전명 `V3.1`과 실제 디렉터리 이름을 구분한다.

## v3.1 데이터 규모 (공식 릴리스 기준)

| 항목 | 값 |
|---|---:|
| Dataset version | `canonical-ai4i-physics-v3.1` |
| 기간 / 간격 | 2026-08-01~2026-08-31 KST / 10분 |
| 사이트 / 자산 | 4개 / 100개 (압축기 20 : CNC 80) |
| `SUPPLIES_AIR_TO` 관계 | 80개 |
| 압축기 / CNC 관측(배치 생성 기준) | 86,400 / 345,600행 |
| 정비 event | 790건 (계획 공구교체 714 + 고장복구 76) |
| Failure truth | 76건 (compressor 20, cnc 56 = PWF14/HDF21/OSF11/TWF6/RNF4) |

gen_data는 이 규모를 "한 번에 배치로" 만드는 대신, 같은 물리 계약을 **실시간으로 조금씩** 만들어낸다는 점만 다르다 — 숫자 자체(자산 100개, 라인 20개, 물리 조건 등)는 전부 이 표를 그대로 따른다.

## 데이터 계보 및 정체성

기획서(§2)가 명시한 프레이밍을 그대로 따르되, 이번 문서에서 계보를 한 단계 더 명확히 한다.

```
Azure PdM / AI4I 2020 (원본 배포 데이터, 그 자체가 시뮬레이션 생성물)
    ↓
초기 압축기·CNC 시뮬레이터 프로토타입 (기획서 §12에서 "sensor_server.py 등"으로 지칭된 산출물)
    ↓ (개선·완성)
predictive_maintenance_canonical (v2 → v3 → v3.1)
    ↓
gen_data (v3.1의 물리 계약을 실시간 프로토콜 캡처 형태로 재구성) ← 본 프로젝트
```

**즉 초기 시뮬레이터는 별도로 존재하는 파일이 아니라, 개선을 거쳐 Canonical V3.1로 완성된 것이다.** 팀 저장소에서의 실제 경로는 `predictive_maintenance_canonical_v3_1/`이며, `gen_data`의 `physics_engine.py`는 이 기준본의 `scripts/generate_canonical_dataset.py`를 호환 facade로 재사용한다. PR #1 단독 checkout에서는 `GEN_DATA_CANONICAL_ROOT`로 외부 기준본을 지정할 수 있다.

`gen_data`는 "실측 데이터를 흉내 내는 1차 생성기"가 아니라, **이미 시뮬레이터인 v3.1을 실시간 스트리밍 형태로 재구성한 3차 파생물**이라는 정체성을 문서·코드 전체에서 유지한다. 어떤 문서·발표 자료에서도 "실제 공장 데이터"라고 표현하지 않는다.

## 핵심 설계 원칙 (기획서 §4 발췌)

| 원칙 | gen_data에서의 의미 |
|---|---|
| Truth/Observation 분리 | gen_data는 내부적으로 고장 스케줄(`episodes`)을 알고 있어야 물리값을 계산할 수 있지만, 그 스케줄 자체는 어떤 출력 파일에도 노출하지 않는다. `GEN_DATA_OUTPUT_DIR`에는 센서 관측값만 존재한다. |
| 계수·임계값은 가정치임을 명시 | gen_data는 v3.1의 물리 계수를 그대로 가져다 쓴다(재유도하지 않음). 원 출처가 "통계적 휴리스틱"이라는 점은 v3.1 문서를 그대로 상속한다. |
| 판단 단위 분리 (Agent 설계) | **gen_data 자체에는 Agent(LLM 호출)가 없다.** 전부 결정론적 시뮬레이션이므로 이 원칙은 "적용 대상 아님"으로 명시한다 — 결정론적으로 계산 가능한 것은 애초에 Agent를 쓰지 않는다는 상위 원칙의 결과다. |

## 정정 사항

이전 버전의 본 문서는 `sensor_server.py`/`pdm_server.zip`을 프로젝트 전체에서 찾지 못했다는 점을 "확인 필요" 항목으로 남겼었다. 이는 잘못된 우려였다 — 위 계보에서 정리한 대로, 그 시뮬레이터의 기능은 파일 하나로 남아있는 게 아니라 **개선을 거쳐 v3.1로 흡수·완성**되었기 때문에 별도로 존재하지 않는 게 정상이다. `gen_data/`가 현재 `.git`/`.gitignore`/빈 `README.md`만 있는 상태인 것도 문제가 아니라, 본 문서 3종(`01_overview.md`~`03_detailed_spec.md`)이 그 구현을 시작하기 위한 설계 문서이기 때문이다.

**현재 확인 사항은 "파일을 찾는 것"이 아니라, `physics_engine.py` facade가 팀의 Canonical V3.1 기준본을 정확히 찾고 필요한 export를 정상적으로 제공하는지 확인하는 것**이며, 이는 §03 상세 스펙에서 다룬다.

## 공식 배포본 연계 정보

Canonical V3.1의 기존 배포본은 GitHub 저장소 **`oosuhada/agentic-ontology-dashboard`**에 정식 릴리스로 태깅되어 있었다. 현재 팀 기준 filesystem 경로는 PR #2의 `predictive_maintenance_canonical_v3_1/`이다.

```
태그: predictive-maintenance-canonical-v3.1-20260805
커밋: 081f56d
릴리스 자산: predictive_maintenance_canonical_v3.1.zip (+ .sha256)
```

**이 저장소 이름이 중요하다** — `agentic-ontology-dashboard`는 이전에 확인했던 대시보드 프로토타입(주간보고의 `prototype/ontology-dashboard-prebuild` 브랜치, 커밋 `af4f270`)과 **동일한 저장소**다. 즉 gen_data가 물리 로직을 가져오는 v3.1과, 데이터를 가공·사용하는 `ontology_dashboard`는 서로 다른 프로젝트가 아니라 **같은 GitHub 저장소의 서로 다른 브랜치/태그**로 존재한다. 앞으로 두 산출물을 "통합해서 보여줘야 하는" 문제(기존 멘토 질문 항목)를 풀 때, 이미 하나의 저장소로 묶여 있다는 사실이 실마리가 될 수 있다.

릴리스 노트가 명시한 물리 계약은 gen_data가 재사용할 함수들의 **공식 스펙**과 정확히 일치한다:

```
power = torque × rpm × 2π / 60
PWF: power < 3,500W or power > 9,000W
HDF: process - air < 8.6K and rpm < 1,380
OSF: tool_wear × torque > L 11,000 / M 12,000 / H 13,000
TWF: tool_wear between 200 and 240 minutes
RNF: condition-independent random failure
```

패키지 구조 자체는 동일하며, 팀 저장소에서의 실제 루트 이름만 underscore 표기를 사용한다. `gen_data/physics_engine.py`가 참조하는 `scripts/` 경로는 다음 구조의 일부다:

```
predictive_maintenance_canonical_v3_1/
├── canonical/{dataset, evaluation_truth, model_outputs, validation}/
├── experiments/connected_air_supply/
├── model/ agent/ api/ scripts/ dashboard/
├── SCHEMA.md
└── RESULT_ARTIFACT_SCHEMA.md
```

**참고용 출처 확인 — v3.1 배포본 자체의 무결성**: 기존 릴리스 노트의 ZIP SHA-256과 번들 체크섬은 과거 배포본 확인용이다. 팀 저장소로 이관된 Canonical V3.1의 무결성·재현성은 PR #2의 `scripts/validate_package.py`와 `scripts/validate_reproducibility.py`가 담당하며, PR #1은 해당 기준본을 변경하거나 재생성하지 않는다.
