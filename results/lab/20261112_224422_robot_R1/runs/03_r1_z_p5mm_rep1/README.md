# R1 z +5 mm #1

- 시행 이름: `r1_z_p5mm_rep1` (세션 `20261112_224422_robot_R1`)
- 단계: R1, 조건: z +5 mm
- 데이터 출처(data_kind): **measured** - 실기기
- 실행 시각(이 PC): 2026-11-12T22:53:18+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE | Peak Error | Lag (r2) | 진폭비 | Overshoot | 정착 시간 |
|---|---|---|---|---|---|---|---|---|
| z | 시행 축 | 5.00 mm | 1.53 mm | 3.77 mm | 263 ms (0.71) | 0.72 | 0.01 mm | 0.00 s |
| stewart_1 | 대표 관절 | 6.82° | 1.46° | 4.36° | 198 ms (0.93) | 0.84 | 0.00° | 0.00 s |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 현재 상태 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
