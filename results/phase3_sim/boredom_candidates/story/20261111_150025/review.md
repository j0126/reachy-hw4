# MuJoCo 검토 자료 (자동 생성)

생성 2026-11-11T06:01:07+00:00 · `python -m reachy_motion sim-verify`. 계획·정책 = computed, MuJoCo 측정 = simulated (마찰 지배적·실시간보다 느림 → 눈으로 판단용, 로봇 추종 예측 아님), tick = pc_measured.

**미검증**: 안테나 방향(droop = right −/left +, perk = 0° 쪽)은 SDK sleep 자세에서 추론했고, roll 부호는 실기기에서 확인하지 않았다. 초기 정책 통과는 기구적 안전 보장이 아니다.

## 1. 실행 결과와 시작·종료 자세 (계획 vs MuJoCo 측정)

| 모션 | 실행 | 정지 후 시작 | 측정 시작 (pitch/yaw/roll °, z mm, 안테나 R/L °) | 측정 종료 | 시작 오차 각/이동/안테나 | 종료 오차 각/이동/안테나 | 측정 최소 관절 여유 | tick (건너뜀) |
|---|---|---|---|---|---|---|---|---|
| boredom:expressive | 완료 | 예 | 0.1/0.0/0.1, -0.1, -10.0/10.0 | 0.1/-0.0/0.0, -0.1, -10.0/10.0 | 0.10°/0.11 mm/0.01° | 0.09°/0.10 mm/0.01° | 34.7° (stewart_3) | 531 (0) |
| boredom:neutral | 완료 | 예 | 0.0/0.0/0.0, -0.1, -10.0/10.0 | 0.1/-0.1/-0.1, -0.1, -10.0/10.0 | 0.05°/0.10 mm/0.01° | 0.09°/0.10 mm/0.01° | 30.0° (stewart_4) | 521 (0) |

계획 시작·종료는 8개 모두 rest(head 0, 안테나 −9.998/+9.998°, 몸통 0). 오차 = |측정 − 계획|의 최댓값.

## 2. 키프레임 (설계값에 배율 적용 = 실제 실행 파라미터)

**boredom:expressive** — 길이 10.60 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | settle | 1.00 | 1.00 | 0.40 | ease_in_out | pitch +8.0, z -4.0 |
| head | look-left | 2.80 | 1.40 | 1.00 | minjerk | pitch +8.0, yaw +25.0, roll +2.0, z -4.0 |
| head | look-right | 6.00 | 2.20 | 0.80 | minjerk | pitch +8.0, yaw -25.0, roll -2.0, z -4.0 |
| head | slump | 7.90 | 1.10 | 1.20 | ease_in_out | pitch +20.0, roll +5.0, z -12.0 |
| head | back | 10.60 | 1.50 | 0.00 | minjerk | rest(0) |
| antennas | wait | 0.20 | 0.20 | 0.00 | minjerk | R -10.0, L +10.0 |
| antennas | lower | 1.20 | 1.00 | 2.60 | ease_in_out | R -35.0, L +35.0 |
| antennas | sag | 6.00 | 2.20 | 1.20 | ease_in_out | R -45.0, L +45.0 |
| antennas | droop | 8.20 | 1.00 | 1.30 | ease_in_out | R -75.0, L +75.0 |
| antennas | recover | 10.60 | 1.10 | 0.00 | minjerk | R -10.0, L +10.0 |

**boredom:neutral** — 길이 10.40 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | look-left | 1.90 | 1.90 | 1.40 | linear | pitch +8.0, yaw +25.0 |
| head | look-right | 7.10 | 3.80 | 1.40 | linear | pitch +8.0, yaw -25.0 |
| head | back | 10.40 | 1.90 | 0.00 | linear | rest(0) |

## 3. Expressive vs Neutral

| 모션 | 계획 같은 시작 / 종료 | 비교 문제 | 길이 E / N s | 측정 시작 차 (각°/이동 mm) | 측정 종료 차 | 기본 동작 일치 (neutral 키 → expressive 키) |
|---|---|---|---|---|---|---|
| boredom | 예 / 예 | 0 | 10.60 / 10.40 | 0.05/0.04 | 0.10/0.10 | ✓ look-left (Δyaw +25.0) → look-left (Δyaw +25.0), slump (Δyaw +25.0); look-right (Δyaw -50.0) → look-right (Δyaw -50.0); back (Δyaw +25.0) → look-left (Δyaw +25.0), slump (Δyaw +25.0) |

## 4. 전체 궤적 검사 (계획, computed, 초기 정책)

| 모션 | 판정 | IK NaN | 최소 관절 여유 ° (관절) | Stewart / 몸통 / 안테나 속도 비 | 최대 roll / pitch / 상대 yaw ° | z 범위 mm | 경고 |
|---|---|---|---|---|---|---|---|
| boredom:expressive | 통과 | 0 | 34.8 (stewart_3) | 0.08 / 0.00 / 0.05 | 5.0 / 20.0 / 25.0 | -12.0…0.0 | draft |
| boredom:neutral | 통과 | 0 | 30.0 (stewart_3) | 0.01 / 0.00 / 0.00 | 0.0 / 8.0 / 25.0 | 0.0…0.0 | velocity_step, draft |

## 5. 눈으로 확인하는 재생 명령 (MuJoCo viewer, 127.0.0.1)

```
.venv\Scripts\python -m reachy_motion sim-play boredom --variant expressive
.venv\Scripts\python -m reachy_motion sim-play boredom --variant neutral
```

재생 후 Enter = 다시, r = 파일 다시 읽기(수정 반영), v = 다른 변형, q = 종료.
