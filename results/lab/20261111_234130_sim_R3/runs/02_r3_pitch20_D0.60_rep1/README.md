# R3 pitch 20°, D 0.6 s #1

- 시행 이름: `r3_pitch20_D0.60_rep1` (세션 `20261111_234130_sim_R3`)
- 단계: R3, 조건: A 20°, D 0.6 s
- 데이터 출처(data_kind): **simulated** - MuJoCo: 마찰이 지배적이고 이 PC에서 실시간의 약 0.84배. 설계와 기록 절차 확인용이며 로봇 추종 예측이 아님 (Phase 1 5.5)
- 실행 시각(이 PC): 2026-11-11T23:41:37+09:00
- 완료: 예

## 결과 (computed from simulated data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| pitch | 시행 축 | 20.00° | 5.30° | 9.44° | 189 ms (0.93) | 0.96 | 0.72° | 0.67 s |
| stewart_4 | 대표 관절 | 14.47° | 3.44° | 6.24° | 166 ms (0.95) | 0.96 | 0.43° | 0.59 s |

## 메모

GUI 사용성 점검 (ux_tasks.py, 첫 사용자 과제 A/B/C)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
