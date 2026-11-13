# R1 yaw +2 deg #1

- 시행 이름: `r1_yaw_p2deg_rep1` (세션 `20261112_221617_robot_R1`)
- 단계: R1, 조건: yaw +2 deg
- 데이터 출처(data_kind): **measured** - 실기기
- 실행 시각(이 PC): 2026-11-12T22:16:18+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| yaw | 시행 축 | 2.00° | 1.07° | 3.05° | 498 ms (-0.61) | 0.18 | 0.11° | 0.00 s |
| stewart_5 | 대표 관절 | 0.60° | 0.32° | 6.79° | 500 ms (-0.59) | 0.15 | 0.08° | 0.00 s |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
