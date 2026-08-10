# Predictive Maintenance Canonical V3.1 Release Verification

> **Historical/reference verification:** 이 문서에서 검증한 model/prediction/Result
> Artifact는 현재 `gen_data` 운영 결과가 아니라 V3.1 migration/regression fixture다.
> 현재 소유권은 `OWNERSHIP_AND_MIGRATION.md`를 따른다.

## 검증 기준

```text
dataset     canonical-ai4i-physics-v3.1
model       independent-logreg-v3.1
experiment  relation-reasoning-agent-eval-v3.1
period      2026-08-01T00:00:00+09:00 ~ 2026-08-31T00:00:00+09:00
seed        42
profile     balanced_demo
```

## 전체 pipeline

다음 순서의 전체 재생성을 통과했다.

```text
canonical dataset + evaluation truth
→ positive/negative agent cases
→ sensor/maintenance evidence smoke fixture
→ package validation
→ model training
→ prediction snapshot/factor/timeline
→ Result Artifact reference fixture
→ full reproducibility validation
```

## 데이터 결과

| 항목 | 결과 |
|---|---:|
| Assets | 100 |
| Relations | 80 |
| Compressor observations | 86,400 |
| CNC observations | 345,600 |
| Production cycles | 170,875 |
| Maintenance events | 790 |
| Failure recovery events | 76 |
| Public agent cases | 20 |
| Prediction timeline | 68,208 |
| Result Artifact reference fixture | 100 |

## Tool wear continuity

| 조건 | 결과 |
|---|---:|
| `running → running` reset | 0 |
| `tool_replaced=1` events | 731 |
| maintenance start와 정렬된 reset | 731 |
| maintenance 없이 발생한 reset | 0 |
| reset 없는 replacement | 0 |

## AI4I physics

```text
corr(air, process)    0.919768
corr(rpm, torque)    -0.845823
process below air     0 / 345600
PWF                  14 / 14
HDF                  21 / 21
OSF                  11 / 11
TWF                   6 / 6
RNF                   4 / 4
```

## Agent evidence

```text
positive upstream accuracy      1.0
negative rejection accuracy     1.0
false upstream claim rate       0.0
maintenance evidence claims     1
maintenance evidence accuracy   1.0
```

존재하지 않는 maintenance ID를 제출하는 negative test에서는 maintenance evidence
accuracy와 해당 case score가 모두 0으로 처리됐다.

## Runtime smoke

- Dataset API 주요 endpoint: PASS
- Evaluation truth 기본 비공개: PASS
- Experiment hidden truth 기본 비공개: PASS
- Replay start/pause/resume/speed/seek/reset: PASS
- SSE `text/event-stream`: PASS

## 재현성 및 변조 검출

- Same seed outputs identical: PASS
- Different seed changes outputs: PASS
- Full scope 5일: PASS
- Full scope 4일 minimum guard: PASS
- Tool-wear running reset tamper: 감지
- Invalid maintenance evidence: 거부

## 배포 원칙

공유할 파일은 Finder나 메신저로 바깥 폴더를 다시 압축한 파일이 아니라 다음
내부 release artifact다.

```text
dist/predictive_maintenance_canonical_v3_1.zip
dist/predictive_maintenance_canonical_v3_1.zip.sha256
```

Release builder는 영문 root, ZIP CRC, 실제 압축 해제, 압축 해제본 package
validation, macOS metadata·venv·cache 제외를 검사한다.
