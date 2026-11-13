# R1 yaw +10 deg #1

- 시행 이름: `r1_yaw_p10deg_rep1` (세션 `20261112_224422_robot_R1`)
- 단계: R1, 조건: yaw +10 deg
- 데이터 출처(data_kind): **measured** - 실기기
- 실행 시각(이 PC): 2026-11-12T22:44:23+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| yaw | 시행 축 | 10.00° | 4.13° | 6.64° | 355 ms (0.31) | 0.53 | 0.07° | 0.01 s |
| stewart_5 | 대표 관절 | 3.23° | 1.61° | 7.69° | 500 ms (0.05) | 0.65 | 0.07° | 0.00 s |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
