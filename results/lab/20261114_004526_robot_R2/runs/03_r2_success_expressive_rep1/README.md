# R2 success:expressive #1

- 시행 이름: `r2_success_expressive_rep1` (세션 `20261114_004526_robot_R2`)
- 단계: R2, 조건: success expressive
- 데이터 출처(data_kind): **measured** - 실제 로봇
- 실행 시각(이 PC): 2026-11-14T00:45:52+09:00
- 완료: 예

## 결과 (computed from measured data)

| 채널 | 역할 | 명령 진폭 | RMSE (지연 포함) | 지연 보정 RMSE | Peak Error (지연 포함) | 지연 Lag (r²) | 진폭비 | Overshoot | 정착 시간 | 정지 중 떨림 RMS |
|---|---|---|---|---|---|---|---|---|---|---|
| pitch | 시행 축 | 19.60° | 5.45° | 1.55° | 17.89° | 153 ms (0.92) | 0.91 | 0.09° | 0.00 s | 0.03° |
| stewart_1 | 대표 관절 | 25.84° | 5.59° | 1.02° | 21.87° | 141 ms (0.97) | 1.00 | 0.07° | 0.00 s | 0.02° |

## 메모

(없음)

## 파일

- `commands.csv` 보낸 명령 / `present_<data_kind>.csv` 측정값 (같은 시간 기준) / `ticks.csv` 실행기 주기 (pc_measured) / `manifest.json` 조건·검사·환경 / `metrics.json` 추종 지표 (SI)
- 다른 PC에서 보기: Motion Lab → ③ 결과 → '다른 폴더 불러오기'로 이 폴더(또는 세션 폴더)를 고르면 같은 그래프와 지표가 나온다.
