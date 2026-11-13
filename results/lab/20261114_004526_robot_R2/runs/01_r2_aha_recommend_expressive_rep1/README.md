# R2 aha_recommend:expressive #1

- 시행 이름: `r2_aha_recommend_expressive_rep1` (세션 `20261114_004526_robot_R2`)
- 단계: R2, 조건: aha_recommend expressive
- 데이터 출처(data_kind): **measured** - 실제 로봇
- 실행 시각(이 PC): 2026-11-14T00:45:27+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE (지연 포함) | 지연 보정 RMSE | Peak Error (지연 포함) | 지연 Lag (r²) | 진폭비 | Overshoot | 정착 시간 | 정지 중 떨림 RMS |
|---|---|---|---|---|---|---|---|---|---|---|
| yaw | 시행 축 | 30.69° | 5.30° | 2.12° | 14.08° | 191 ms (0.96) | 0.97 | 0.51° | 0.04 s | 0.02° |
| stewart_1 | 대표 관절 | 29.30° | 5.13° | 1.25° | 25.62° | 163 ms (0.98) | 1.02 | 0.00° | 0.00 s | 0.00° |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 측정값 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
