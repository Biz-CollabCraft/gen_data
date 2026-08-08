# Predictive Maintenance Canonical V3.1 변경 내역

V3.1은 V3의 AI4I 물리 계약과 Result Artifact 구조를 유지하면서, 두 차례 팀
리뷰에서 확인된 공구 마모 상태 전이·검증·에이전트 증거·문서 정합성 문제를
수정한 배포 기준본이다.

## 배포 차단 결함 수정

### 공구 마모 초기화 시점

- 공구 교체를 결정한 `running` 행에서는 기존 `tool_wear_min`을 유지한다.
- 초기화는 `maintenance_event.started_at`과 같은 tick에서 수행한다.
- 해당 sensor 행은 `operating_state=maintenance`, `is_operating=0`이다.
- TWF/OSF 고장 시각의 높은 wear 값은 보존하고, 첫 maintenance tick에서만
  reset한다.

### Tool wear continuity release gate

`scripts/validate_package.py`는 다음을 모두 검사한다.

- `running → running` 상태에서 1.0분 초과 감소 0건
- 큰 reset은 `maintenance` 상태에서만 허용
- 모든 reset은 `tool_replaced=1` 정비 이벤트 시작 시각과 일치
- 모든 `tool_replaced=1` 정비 이벤트에는 대응 reset이 존재

현재 30일 seed 42 결과:

```text
running reset                         0
tool replacement event             731
aligned reset transition           731
reset without maintenance            0
replacement without reset            0
```

## Agent evidence 계약 보강

`evidence_observations[]`는 다음 유형을 지원한다.

```text
sensor
maintenance
```

Maintenance evidence는 `maintenance_id`, 유형, 시작·완료 시각,
`tool_replaced`를 canonical `maintenance_event.csv`와 대조한다. 예제에는 실제
계획 공구 교체 근거 1건이 포함되며, 잘못된 maintenance ID는 점수 0으로
거부된다.

## 문서 정합성

- RPM 생성식을 실제 구현인 0.30 inverse-power blend로 명시
- PWF low-power 분기의 torque 사전 조정과 RPM 역산 순서 문서화
- Production cycle feature는 future leakage를 막는 as-of join 검증 이후 추가하는
  후속 계획으로 명시

## 버전

```text
dataset     canonical-ai4i-physics-v3.1
model       independent-logreg-v3.1
experiment  relation-reasoning-agent-eval-v3.1
```

이번 작업에서는 `predictive_maintenance_canonical_v3.1/`을 별도 배포 폴더로
생성했다. 신규 MVP 연동과 팀 공유에는 이 V3.1 폴더와 내부 `dist/` ZIP만
사용한다. 이름이 `predictive_maintenance_canonical_v3/`인 기존 작업 폴더는
과거 작업 경로와 호환 흔적이 섞여 있을 수 있으므로 V3.0 배포 기준본으로
간주하지 않는다.
