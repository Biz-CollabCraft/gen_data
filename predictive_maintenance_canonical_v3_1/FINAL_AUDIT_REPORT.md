# Predictive Maintenance Canonical V3.1 Final Audit

## 판정

V3.1은 AI4I 물리 관계, failure condition, tool-wear continuity,
negative agent control, Result Artifact를 포함한 공유 가능한 데이터 기준본이다.

## Release gates

| Gate | 결과 |
|---|---|
| Canonical/truth/model/experiment 분리 | PASS |
| Canonical SHA-256 | PASS |
| Evaluation truth SHA-256 | PASS |
| Topology 및 observation key | PASS |
| Failure-maintenance 1:1 | PASS |
| Tool wear running continuity | PASS |
| Tool replacement/reset timestamp alignment | PASS |
| AI4I air/process relation | PASS |
| AI4I torque/RPM relation | PASS |
| AI4I sensor dispersion | PASS |
| PWF/HDF/OSF/TWF/RNF condition | PASS |
| Positive experiment observability | PASS |
| Negative local-only isolation | PASS |
| Positive/negative evaluator | PASS |
| Maintenance evidence canonical matching | PASS |
| Model-dataset binding | PASS |
| Prediction timeline contract | PASS |
| Result Artifact contract | PASS |
| Same-seed reproducibility | PASS |
| Different-seed variation | PASS |
| Dataset API 및 Result Artifact endpoint | PASS |
| Replay controls 및 SSE | PASS |
| AI4I physics tamper detection | PASS |
| Failure-condition tamper detection | PASS |
| Tool-wear continuity tamper detection | PASS |
| Negative upstream-isolation tamper detection | PASS |
| Invalid maintenance evidence rejection | PASS |

## AI4I 결과

```text
corr(air, process)       0.919768
corr(rpm, torque)       -0.845823
process below air        0 / 345600
air std                  1.953310
process std              1.512621
rpm std                185.895344
torque std              10.563547
```

```text
PWF 14/14
HDF 21/21
OSF 11/11
TWF  6/6
RNF  4/4
```

AI4I 조건은 서로 배타적이지 않다. 예를 들어 HDF의 낮은 RPM이 PWF low-power
조건과 동시에 겹치거나, OSF의 높은 tool wear가 TWF 구간과 겹칠 수 있다.
Validation은 truth event가 자기 정의 조건을 만족하는지를 release gate로 삼고,
겹치는 조건 수도 별도 기록한다.

## Agent benchmark 결과

```text
positive_upstream_relation 16
negative_local_only         4
```

Smoke fixture:

```text
positive upstream accuracy  1.0
negative rejection accuracy 1.0
false upstream claim rate   0.0
maintenance evidence claims 1
maintenance evidence accuracy 1.0
```

Smoke case 두 건은 formal score에서 제외한다.

## Result Artifact

100개 자산 모두 공통 schema를 충족한다. 각 artifact는 probability, generic
predicted class, status grade, Top-3 factors, recommended action, provenance를
포함한다.

현재 모델은 multiclass failure-mode 모델이 아니므로 PWF/HDF/OSF/TWF를 직접
예측한다고 주장하지 않는다.

## 남은 비차단 항목

- Pure-normal negative agent case
- Confounding/temporally coincident negative case
- Multiclass failure-mode classifier
- Serialized production model artifact
- 실제 설비 stream adapter
- Production cycle의 제품 유형·절삭 시간·공구 마모 증가량을 모델 feature로
  추가하는 as-of join. 미래 cycle이나 정비 이후 정보를 섞지 않도록
  `cycle_completed_at <= prediction observed_at` 계약과 leakage test를 먼저
  구현한 뒤 별도 모델 버전으로 평가한다.

위 항목은 V3.1 canonical 데이터 공유를 막는 결함이 아니라 후속 제품·평가 확장이다.

## 배포 검증

배포본은 영문 루트 `predictive_maintenance_canonical_v3_1/`에서 생성했다.

```text
dist/predictive_maintenance_canonical_v3_1.zip
dist/predictive_maintenance_canonical_v3_1.zip.sha256
```

- ZIP CRC: PASS
- 실제 압축 해제: PASS
- 압축 해제본 package validation: PASS
- macOS metadata·venv·cache 누수: 0건

배포본 식별은 ZIP과 함께 생성되는 `dist/*.sha256`을 최종 기준으로 사용한다.

