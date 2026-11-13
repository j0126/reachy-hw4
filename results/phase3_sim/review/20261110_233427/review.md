# MuJoCo 검토 자료 (자동 생성)

생성 2026-11-10T14:35:34+00:00 · `python -m reachy_motion sim-verify`. 계획·정책 = computed, MuJoCo 측정 = simulated (마찰 지배적·실시간보다 느림 → 눈으로 판단용, 로봇 추종 예측 아님), tick = pc_measured.

**미검증**: 안테나 방향(droop = right −/left +, perk = 0° 쪽)은 SDK sleep 자세에서 추론했고, roll 부호는 실기기에서 확인하지 않았다. 초기 정책 통과는 기구적 안전 보장이 아니다.

## 1. 실행 결과와 시작·종료 자세 (계획 vs MuJoCo 측정)

| 모션 | 실행 | 정지 후 시작 | 측정 시작 (pitch/yaw/roll °, z mm, 안테나 R/L °) | 측정 종료 | 시작 오차 각/이동/안테나 | 종료 오차 각/이동/안테나 | 측정 최소 관절 여유 | tick (건너뜀) |
|---|---|---|---|---|---|---|---|---|
| aha_recommend:expressive | 완료 | 예 | 0.1/0.0/0.1, -0.1, -10.0/10.0 | 0.0/0.1/0.1, -0.1, -10.0/10.0 | 0.09°/0.10 mm/0.01° | 0.08°/0.09 mm/0.01° | 31.0° (stewart_1) | 154 (0) |
| aha_recommend:neutral | 완료 | 예 | 0.0/0.0/0.0, -0.1, -10.0/10.0 | 0.0/0.1/0.1, -0.1, -10.0/10.0 | 0.04°/0.10 mm/0.01° | 0.10°/0.10 mm/0.01° | 33.9° (stewart_3) | 131 (0) |
| boredom:expressive | 완료 | 예 | 0.0/0.0/0.1, -0.1, -10.0/10.0 | 0.1/0.0/0.1, -0.1, -10.0/10.0 | 0.07°/0.10 mm/0.01° | 0.10°/0.10 mm/0.01° | 37.1° (stewart_3) | 321 (0) |
| boredom:neutral | 완료 | 예 | 0.1/0.0/0.0, -0.1, -10.0/10.0 | 0.1/0.1/0.1, -0.1, -10.0/10.0 | 0.06°/0.10 mm/0.01° | 0.10°/0.10 mm/0.01° | 30.0° (stewart_3) | 301 (0) |
| success:expressive | 완료 | 예 | 0.0/0.0/0.1, -0.1, -10.0/10.0 | -0.1/0.0/-0.0, -0.1, -10.0/10.0 | 0.07°/0.10 mm/0.01° | 0.10°/0.09 mm/0.01° | 31.9° (stewart_6) | 106 (0) |
| success:neutral | 완료 | 예 | -0.1/0.0/-0.0, -0.1, -10.0/10.0 | 0.1/-0.0/0.0, -0.1, -10.0/10.0 | 0.06°/0.09 mm/0.01° | 0.10°/0.10 mm/0.01° | 39.4° (stewart_3) | 101 (0) |
| failure:expressive | 완료 | 예 | 0.1/-0.0/0.0, -0.1, -10.0/10.0 | 0.1/-0.0/0.0, -0.1, -10.0/10.0 | 0.06°/0.10 mm/0.01° | 0.10°/0.10 mm/0.01° | 39.8° (stewart_1) | 186 (0) |
| failure:neutral | 완료 | 예 | 0.1/-0.0/0.0, -0.1, -10.0/10.0 | 0.0/-0.1/-0.1, -0.1, -10.0/10.0 | 0.07°/0.10 mm/0.01° | 0.08°/0.10 mm/0.01° | 41.2° (stewart_3) | 101 (0) |

계획 시작·종료는 8개 모두 rest(head 0, 안테나 −9.998/+9.998°, 몸통 0). 오차 = |측정 − 계획|의 최댓값.

## 2. 키프레임 (설계값에 배율 적용 = 실제 실행 파라미터)

**aha_recommend:expressive** — 길이 3.05 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | think | 0.45 | 0.45 | 0.15 | ease_in_out | pitch +6.0, yaw -8.0, roll +4.0 |
| head | pop | 1.05 | 0.45 | 0.20 | cartoon | pitch -12.0, z +5.0 |
| head | present | 1.75 | 0.50 | 0.60 | minjerk | pitch +4.0, yaw +22.0, roll -6.0 |
| head | back | 3.05 | 0.70 | 0.00 | minjerk | rest(0) |
| antennas | droop | 0.45 | 0.45 | 0.20 | minjerk | R -30.0, L +30.0 |
| antennas | perk | 1.10 | 0.45 | 0.15 | cartoon | R +5.0, L -5.0 |
| antennas | wiggle-a | 1.40 | 0.15 | 0.00 | ease_in_out | R -5.0, L +5.0 |
| antennas | wiggle-b | 1.55 | 0.15 | 0.60 | ease_in_out | R +5.0, L -5.0 |
| antennas | settle | 2.75 | 0.60 | 0.00 | minjerk | R -10.0, L +10.0 |

**aha_recommend:neutral** — 길이 2.60 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | present | 0.90 | 0.90 | 0.80 | linear | pitch +4.0, yaw +22.0 |
| head | back | 2.60 | 0.90 | 0.00 | linear | rest(0) |

**boredom:expressive** — 길이 6.40 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | slump | 1.20 | 1.20 | 0.80 | ease_in_out | pitch +12.0, roll +5.0, z -8.0 |
| head | glance-away | 3.00 | 1.00 | 0.70 | minjerk | pitch +8.0, yaw +25.0, roll +3.0, z -6.0 |
| head | sigh | 4.50 | 0.80 | 0.50 | ease_in_out | pitch +16.0, roll +4.0, z -10.0 |
| head | back | 6.40 | 1.40 | 0.00 | minjerk | rest(0) |
| antennas | wait | 0.30 | 0.30 | 0.00 | minjerk | R -10.0, L +10.0 |
| antennas | droop | 1.90 | 1.60 | 1.20 | ease_in_out | R -60.0, L +60.0 |
| antennas | twitch | 3.40 | 0.30 | 0.00 | minjerk | R -45.0, L +60.0 |
| antennas | untwitch | 3.70 | 0.30 | 1.50 | minjerk | R -60.0, L +60.0 |
| antennas | recover | 6.40 | 1.20 | 0.00 | minjerk | R -10.0, L +10.0 |

**boredom:neutral** — 길이 6.00 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | glance-away | 2.00 | 2.00 | 2.00 | linear | pitch +8.0, yaw +25.0 |
| head | back | 6.00 | 2.00 | 0.00 | linear | rest(0) |

**success:expressive** — 길이 2.10 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | crouch | 0.30 | 0.30 | 0.00 | ease_in_out | pitch +6.0, z -5.0 |
| head | pop | 0.80 | 0.50 | 0.15 | cartoon | pitch -10.0, z +5.0 |
| head | nod-down | 1.25 | 0.30 | 0.00 | minjerk | pitch +8.0 |
| head | nod-up | 1.55 | 0.30 | 0.00 | minjerk | pitch -4.0 |
| head | back | 2.10 | 0.55 | 0.00 | minjerk | rest(0) |
| antennas | wait | 0.30 | 0.30 | 0.00 | minjerk | R -10.0, L +10.0 |
| antennas | perk | 0.70 | 0.40 | 0.00 | cartoon | R +15.0, L -15.0 |
| antennas | wiggle-a | 0.85 | 0.15 | 0.00 | ease_in_out | R -5.0, L +5.0 |
| antennas | wiggle-b | 1.00 | 0.15 | 0.00 | ease_in_out | R +15.0, L -15.0 |
| antennas | wiggle-c | 1.15 | 0.15 | 0.00 | ease_in_out | R -5.0, L +5.0 |
| antennas | settle | 1.75 | 0.60 | 0.00 | minjerk | R -10.0, L +10.0 |

**success:neutral** — 길이 2.00 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | nod-down | 0.50 | 0.50 | 0.00 | linear | pitch +10.0 |
| head | nod-up | 1.00 | 0.50 | 0.00 | linear | rest(0) |
| head | nod-down-2 | 1.50 | 0.50 | 0.00 | linear | pitch +10.0 |
| head | back | 2.00 | 0.50 | 0.00 | linear | rest(0) |

**failure:expressive** — 길이 3.70 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | flinch | 0.20 | 0.20 | 0.00 | ease_in_out | pitch -4.0, z +3.0 |
| head | slump | 1.10 | 0.90 | 0.40 | ease_in_out | pitch +18.0, roll -8.0, z -8.0 |
| head | shake-left | 1.85 | 0.35 | 0.00 | minjerk | pitch +16.0, yaw +10.0, roll -6.0, z -8.0 |
| head | shake-right | 2.20 | 0.35 | 0.00 | minjerk | pitch +16.0, yaw -10.0, roll -6.0, z -8.0 |
| head | center | 2.50 | 0.30 | 0.30 | minjerk | pitch +16.0, roll -6.0, z -8.0 |
| head | recover | 3.70 | 0.90 | 0.00 | minjerk | rest(0) |
| antennas | wait | 0.30 | 0.30 | 0.00 | minjerk | R -10.0, L +10.0 |
| antennas | droop | 1.20 | 0.90 | 1.40 | ease_in_out | R -80.0, L +80.0 |
| antennas | recover | 3.60 | 1.00 | 0.00 | minjerk | R -10.0, L +10.0 |

**failure:neutral** — 길이 2.00 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | left | 0.50 | 0.50 | 0.00 | linear | yaw +12.0 |
| head | right | 1.50 | 1.00 | 0.00 | linear | yaw -12.0 |
| head | center | 2.00 | 0.50 | 0.00 | linear | rest(0) |

## 3. Expressive vs Neutral

| 모션 | 계획 같은 시작 / 종료 | 비교 문제 | 길이 E / N s | 측정 시작 차 (각°/이동 mm) | 측정 종료 차 | 기본 동작 일치 (neutral 키 → expressive 키) |
|---|---|---|---|---|---|---|
| aha_recommend | 예 / 예 | 0 | 3.05 / 2.60 | 0.09/0.07 | 0.04/0.02 | ✓ present (Δyaw +22.0) → present (Δyaw +22.0); back (Δyaw -22.0) → back (Δyaw -22.0) |
| boredom | 예 / 예 | 0 | 6.40 / 6.00 | 0.04/0.03 | 0.05/0.05 | ✓ glance-away (Δyaw +25.0) → glance-away (Δyaw +25.0); back (Δyaw -25.0) → sigh (Δyaw -25.0) |
| success | 예 / 예 | 0 | 2.10 / 2.00 | 0.11/0.08 | 0.20/0.16 | ✓ nod-down (Δpitch +10.0) → crouch (Δpitch +6.0), nod-down (Δpitch +18.0); nod-up (Δpitch -10.0) → pop (Δpitch -16.0), nod-up (Δpitch -12.0); nod-down-2 (Δpitch +10.0) → crouch (Δpitch +6.0), nod-down (Δpitch +18.0); back (Δpitch -10.0) → pop (Δpitch -16.0), nod-up (Δpitch -12.0) |
| failure | 예 / 예 | 0 | 3.70 / 2.00 | 0.00/0.00 | 0.10/0.10 | ✓ left (Δyaw +12.0) → shake-left (Δyaw +10.0), center (Δyaw +10.0); right (Δyaw -24.0) → shake-right (Δyaw -20.0); center (Δyaw +12.0) → shake-left (Δyaw +10.0), center (Δyaw +10.0) |

## 4. 전체 궤적 검사 (계획, computed, 초기 정책)

| 모션 | 판정 | IK NaN | 최소 관절 여유 ° (관절) | Stewart / 몸통 / 안테나 속도 비 | 최대 roll / pitch / 상대 yaw ° | z 범위 mm | 경고 |
|---|---|---|---|---|---|---|---|
| aha_recommend:expressive | 통과 | 0 | 28.9 (stewart_6) | 0.32 / 0.00 / 0.18 | 6.0 / 13.8 / 22.0 | -0.5…5.5 | cartoon_overshoot, draft |
| aha_recommend:neutral | 통과 | 0 | 33.8 (stewart_3) | 0.02 / 0.00 / 0.00 | 0.0 / 4.0 / 22.0 | 0.0…0.0 | velocity_step, draft |
| boredom:expressive | 통과 | 0 | 37.2 (stewart_3) | 0.07 / 0.00 / 0.04 | 5.0 / 16.0 / 25.0 | -10.0…0.0 | draft |
| boredom:neutral | 통과 | 0 | 30.0 (stewart_3) | 0.01 / 0.00 / 0.00 | 0.0 / 8.0 / 25.0 | 0.0…0.0 | velocity_step, draft |
| success:expressive | 통과 | 0 | 29.4 (stewart_1) | 0.37 / 0.00 / 0.15 | 0.0 / 11.6 / 0.0 | -6.0…6.0 | cartoon_overshoot, draft |
| success:neutral | 통과 | 0 | 37.1 (stewart_3) | 0.02 / 0.00 / 0.00 | 0.0 / 10.0 / 0.0 | 0.0…0.0 | velocity_step, draft |
| failure:expressive | 통과 | 0 | 38.0 (stewart_1) | 0.10 / 0.00 / 0.07 | 8.0 / 18.0 / 10.0 | -8.0…3.0 | draft |
| failure:neutral | 통과 | 0 | 40.2 (stewart_1) | 0.01 / 0.00 / 0.00 | 0.0 / 0.0 / 12.0 | 0.0…0.0 | velocity_step, draft |

## 5. 눈으로 확인하는 재생 명령 (MuJoCo viewer, 127.0.0.1)

```
.venv\Scripts\python -m reachy_motion sim-play aha_recommend --variant expressive
.venv\Scripts\python -m reachy_motion sim-play aha_recommend --variant neutral
.venv\Scripts\python -m reachy_motion sim-play boredom --variant expressive
.venv\Scripts\python -m reachy_motion sim-play boredom --variant neutral
.venv\Scripts\python -m reachy_motion sim-play success --variant expressive
.venv\Scripts\python -m reachy_motion sim-play success --variant neutral
.venv\Scripts\python -m reachy_motion sim-play failure --variant expressive
.venv\Scripts\python -m reachy_motion sim-play failure --variant neutral
```

재생 후 Enter = 다시, r = 파일 다시 읽기(수정 반영), v = 다른 변형, q = 종료.
