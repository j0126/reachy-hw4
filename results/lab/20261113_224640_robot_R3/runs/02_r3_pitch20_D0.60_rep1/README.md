# R3 pitch 20°, D 0.6 s #1

- 시행 이름: `r3_pitch20_D0.60_rep1` (세션 `20261113_224640_robot_R3`)
- 단계: R3, 조건: A 20°, D 0.6 s
- 데이터 출처(data_kind): **measured** - 실기기
- 실행 시각(이 PC): 2026-11-13T22:46:52+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| pitch | 시행 축 | 20.00° | 4.59° | 12.64° | 164 ms (0.98) | 0.89 | 0.05° | 0.04 s |
| stewart_4 | 대표 관절 | 14.47° | 3.36° | 8.34° | 159 ms (0.99) | 0.97 | 0.09° | 0.04 s |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
