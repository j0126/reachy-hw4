# R2 aha_recommend:expressive #1

- 시행 이름: `r2_aha_recommend_expressive_rep1` (세션 `20261111_234112_sim_R2`)
- 단계: R2, 조건: aha_recommend expressive
- 데이터 출처(data_kind): **simulated** - MuJoCo: 마찰이 지배적이고 이 PC에서 실시간의 약 0.84배. 설계와 기록 절차 확인용이며 로봇 추종 예측이 아님 (Phase 1 5.5)
- 실행 시각(이 PC): 2026-11-11T23:41:14+09:00
- 완료: 예

## 결과 (computed from simulated data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| yaw | 시행 축 | 30.69° | 3.83° | 9.41° | 142 ms (0.99) | 0.97 | 0.33° | 0.46 s |
| stewart_1 | 대표 관절 | 29.30° | 3.23° | 15.22° | 98 ms (0.99) | 0.86 | 0.13° | 0.61 s |

## 메모

GUI 사용성 점검 (ux_tasks.py, 첫 사용자 과제 A/B/C)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
