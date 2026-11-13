# R2 aha_recommend:neutral #1

- 시행 이름: `r2_aha_recommend_neutral_rep1` (세션 `20261111_234112_sim_R2`)
- 단계: R2, 조건: aha_recommend neutral
- 데이터 출처(data_kind): **simulated** - MuJoCo: 마찰이 지배적이고 이 PC에서 실시간의 약 0.84배. 설계와 기록 절차 확인용이며 로봇 추종 예측이 아님 (Phase 1 5.5)
- 실행 시각(이 PC): 2026-11-11T23:41:21+09:00
- 완료: 예

## 결과 (computed from simulated data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| yaw | 시행 축 | 22.00° | 4.88° | 6.67° | 271 ms (0.98) | 0.95 | 0.44° | 0.55 s |
| stewart_3 | 대표 관절 | 10.34° | 1.97° | 2.82° | 227 ms (0.99) | 1.00 | 0.13° | 0.38 s |

## 메모

GUI 사용성 점검 (ux_tasks.py, 첫 사용자 과제 A/B/C)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
