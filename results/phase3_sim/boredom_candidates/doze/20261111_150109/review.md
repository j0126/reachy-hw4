# MuJoCo 검토 자료 (자동 생성)

생성 2026-11-11T06:01:45+00:00 · `python -m reachy_motion sim-verify`. 계획·정책 = computed, MuJoCo 측정 = simulated (마찰 지배적·실시간보다 느림 → 눈으로 판단용, 로봇 추종 예측 아님), tick = pc_measured.

**미검증**: 안테나 방향(droop = right −/left +, perk = 0° 쪽)은 SDK sleep 자세에서 추론했고, roll 부호는 실기기에서 확인하지 않았다. 초기 정책 통과는 기구적 안전 보장이 아니다.

## 1. 실행 결과와 시작·종료 자세 (계획 vs MuJoCo 측정)

| 모션 | 실행 | 정지 후 시작 | 측정 시작 (pitch/yaw/roll °, z mm, 안테나 R/L °) | 측정 종료 | 시작 오차 각/이동/안테나 | 종료 오차 각/이동/안테나 | 측정 최소 관절 여유 | tick (건너뜀) |
|---|---|---|---|---|---|---|---|---|
| boredom:expressive | 완료 | 예 | 0.1/0.0/0.1, -0.1, -10.0/10.0 | -0.1/0.0/-0.0, -0.1, -10.0/10.0 | 0.10°/0.10 mm/0.01° | 0.09°/0.09 mm/0.01° | 37.3° (stewart_1) | 354 (0) |
| boredom:neutral | 완료 | 예 | -0.1/0.0/-0.0, -0.1, -10.0/10.0 | 0.1/0.0/0.1, -0.1, -10.0/10.0 | 0.05°/0.09 mm/0.01° | 0.11°/0.10 mm/0.01° | 32.8° (stewart_3) | 341 (0) |

계획 시작·종료는 8개 모두 rest(head 0, 안테나 −9.998/+9.998°, 몸통 0). 오차 = |측정 − 계획|의 최댓값.

## 2. 키프레임 (설계값에 배율 적용 = 실제 실행 파라미터)

**boredom:expressive** — 길이 7.05 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | drift-down | 1.60 | 1.60 | 0.30 | ease_in_out | pitch +10.0, roll +3.0, z -6.0 |
| head | catch | 2.30 | 0.40 | 0.20 | ease_in_out | pitch +6.0, roll +1.0, z -3.0 |
| head | nod-off | 4.50 | 2.00 | 0.80 | ease_in_out | pitch +22.0, roll +6.0, z -14.0 |
| head | snap-awake | 5.65 | 0.35 | 0.40 | minjerk | pitch -6.0, z +3.0 |
| head | settle | 7.05 | 1.00 | 0.00 | minjerk | rest(0) |
| antennas | wait | 0.30 | 0.30 | 0.00 | minjerk | R -10.0, L +10.0 |
| antennas | sag | 1.90 | 1.60 | 0.00 | ease_in_out | R -45.0, L +45.0 |
| antennas | flick | 2.20 | 0.30 | 0.30 | minjerk | R -35.0, L +35.0 |
| antennas | sag-deep | 4.70 | 2.20 | 0.60 | ease_in_out | R -90.0, L +90.0 |
| antennas | perk | 5.55 | 0.25 | 0.50 | minjerk | R +5.0, L -5.0 |
| antennas | settle | 7.05 | 1.00 | 0.00 | minjerk | R -10.0, L +10.0 |

**boredom:neutral** — 길이 6.80 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | look-down | 2.40 | 2.40 | 2.00 | linear | pitch +16.0 |
| head | back | 6.80 | 2.40 | 0.00 | linear | rest(0) |

## 3. Expressive vs Neutral

| 모션 | 계획 같은 시작 / 종료 | 비교 문제 | 길이 E / N s | 측정 시작 차 (각°/이동 mm) | 측정 종료 차 | 기본 동작 일치 (neutral 키 → expressive 키) |
|---|---|---|---|---|---|---|
| boredom | 예 / 예 | 0 | 7.05 / 6.80 | 0.15/0.12 | 0.20/0.16 | ✓ look-down (Δpitch +16.0) → drift-down (Δpitch +10.0), nod-off (Δpitch +16.0); back (Δpitch -16.0) → snap-awake (Δpitch -28.0) |

## 4. 전체 궤적 검사 (계획, computed, 초기 정책)

| 모션 | 판정 | IK NaN | 최소 관절 여유 ° (관절) | Stewart / 몸통 / 안테나 속도 비 | 최대 roll / pitch / 상대 yaw ° | z 범위 mm | 경고 |
|---|---|---|---|---|---|---|---|
| boredom:expressive | 통과 | 0 | 37.0 (stewart_1) | 0.31 / 0.00 / 0.31 | 6.0 / 22.0 / 0.4 | -14.0…3.0 | draft |
| boredom:neutral | 통과 | 0 | 32.7 (stewart_3) | 0.01 / 0.00 / 0.00 | 0.0 / 16.0 / 0.0 | 0.0…0.0 | velocity_step, draft |

## 5. 눈으로 확인하는 재생 명령 (MuJoCo viewer, 127.0.0.1)

```
.venv\Scripts\python -m reachy_motion sim-play boredom --variant expressive
.venv\Scripts\python -m reachy_motion sim-play boredom --variant neutral
```

재생 후 Enter = 다시, r = 파일 다시 읽기(수정 반영), v = 다른 변형, q = 종료.
