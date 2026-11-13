# R1 antenna_right +30 deg #1

- 시행 이름: `r1_antenna_right_p30deg_rep1` (세션 `20261112_224422_robot_R1`)
- 단계: R1, 조건: antenna_right +30 deg
- 데이터 출처(data_kind): **measured** - 실기기
- 실행 시각(이 PC): 2026-11-12T22:53:09+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| antenna_right | 시행 축 | 30.00° | 2.10° | 4.75° | 68 ms (1.00) | 1.01 | 0.08° | 0.00 s |
| stewart_1 | 대표 관절 | 0.00° | - | 0.57° | - (-) | - | - | - s |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
