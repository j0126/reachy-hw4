# R3 pitch 20°, D 1 s #1

- 시행 이름: `r3_pitch20_D1.00_rep1` (세션 `20261112_223651_robot_R3`)
- 단계: R3, 조건: A 20°, D 1 s
- 데이터 출처(data_kind): **measured** - 실기기
- 실행 시각(이 PC): 2026-11-12T22:36:52+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| pitch | 시행 축 | 20.00° | 3.84° | 8.84° | 188 ms (0.97) | 1.03 | 0.04° | 0.00 s |
| stewart_4 | 대표 관절 | 14.47° | 2.80° | 6.62° | 181 ms (0.97) | 1.14 | 0.07° | 0.00 s |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
