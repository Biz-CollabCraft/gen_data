# Dashboard Replay Integration

> 이 문서는 Canonical V3.1 **reference replay UI fixture**를 설명한다. 실제 제품
> Frontend/Report의 운영 입력은 `ontology_dashboard` Backend가 생성·제공하는 Result
> Artifact/Evidence이며, 이 패키지의 precomputed prediction을 운영 SoT로 사용하지 않는다.

reference replay 화면은 `api/replay_server.py`의 SSE를 구독하고 서버가 제공하는
simulation clock을 단일 시간 기준으로 사용한다.

## 권장 UI

- Start / Pause / Resume / Reset
- Speed: `1x`, `6x`, `30x`, `60x`, `360x`
- Timeline scrubber 및 ISO 시각 seek
- 현재 simulation time
- 설비별 최신 센서 카드
- 위험도와 Top-3 factor
- 생산 완료·정비 시작 event feed

## SSE 예시

```javascript
const source = new EventSource("http://127.0.0.1:8001/simulation/events");

source.addEventListener("simulation", (event) => {
  const payload = JSON.parse(event.data);
  renderSimulationStatus(payload.status);
  renderSensors(payload.snapshot.compressor_observations, payload.snapshot.cnc_observations);
  renderPredictions(payload.snapshot.predictions);
});
```

## Seek 주의사항

클라이언트가 rolling feature를 다시 계산하지 않는다. Replay Server가 현재 시점 이전의 가장 가까운 사전 계산 prediction timeline을 함께 반환한다.

## 데이터 의미

- canonical sensor 값은 검증된 CSV 원본이다.
- prediction과 factor는 V3.1 regression/reference fixture다.
- optional experiment는 실제 산업 인과 증거가 아니다.
- UI에서 synthetic / derived / canonical source 표기를 구분한다.
