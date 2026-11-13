# MuJoCo 검토 자료 (자동 생성)

생성 2026-11-11T06:00:23+00:00 · `python -m reachy_motion sim-verify`. 계획·정책 = computed, MuJoCo 측정 = simulated (마찰 지배적·실시간보다 느림 → 눈으로 판단용, 로봇 추종 예측 아님), tick = pc_measured.

**미검증**: 안테나 방향(droop = right −/left +, perk = 0° 쪽)은 SDK sleep 자세에서 추론했고, roll 부호는 실기기에서 확인하지 않았다. 초기 정책 통과는 기구적 안전 보장이 아니다.

## 1. 실행 결과와 시작·종료 자세 (계획 vs MuJoCo 측정)

| 모션 | 실행 | 정지 후 시작 | 측정 시작 (pitch/yaw/roll °, z mm, 안테나 R/L °) | 측정 종료 | 시작 오차 각/이동/안테나 | 종료 오차 각/이동/안테나 | 측정 최소 관절 여유 | tick (건너뜀) |
|---|---|---|---|---|---|---|---|---|
| boredom:expressive | 완료 | 예 | 0.1/0.0/0.1, -0.1, -10.0/10.0 | 0.1/-0.0/0.0, -0.1, -10.0/10.0 | 0.09°/0.10 mm/0.01° | 0.10°/0.10 mm/0.01° | 37.1° (stewart_3) | 431 (0) |
| boredom:neutral | 완료 | 예 | 0.1/-0.0/0.0, -0.1, -10.0/10.0 | 0.1/-0.1/-0.1, -0.1, -10.0/10.0 | 0.05°/0.10 mm/0.01° | 0.08°/0.10 mm/0.01° | 31.3° (stewart_4) | 421 (0) |

계획 시작·종료는 8개 모두 rest(head 0, 안테나 −9.998/+9.998°, 몸통 0). 오차 = |측정 − 계획|의 최댓값.

## 2. 키프레임 (설계값에 배율 적용 = 실제 실행 파라미터)

**boredom:expressive** — 길이 8.60 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | slump | 1.00 | 1.00 | 0.30 | ease_in_out | pitch +12.0, roll +4.0, z -8.0 |
| head | look-left | 2.50 | 1.20 | 0.70 | minjerk | pitch +6.0, yaw +25.0, roll +3.0, z -5.0 |
| head | look-right | 5.20 | 2.00 | 0.70 | minjerk | pitch +6.0, yaw -25.0, roll -3.0, z -5.0 |
| head | sigh | 6.80 | 0.90 | 0.50 | ease_in_out | pitch +16.0, roll +4.0, z -10.0 |
| head | back | 8.60 | 1.30 | 0.00 | minjerk | rest(0) |
| antennas | wait | 0.30 | 0.30 | 0.00 | minjerk | R -10.0, L +10.0 |
| antennas | droop | 1.30 | 1.00 | 0.90 | ease_in_out | R -50.0, L +50.0 |
| antennas | perk-left | 2.60 | 0.40 | 0.50 | minjerk | R -25.0, L +25.0 |
| antennas | fall-left | 3.70 | 0.60 | 1.40 | ease_in_out | R -55.0, L +55.0 |
| antennas | perk-right | 5.50 | 0.40 | 0.40 | minjerk | R -25.0, L +25.0 |
| antennas | droop-deep | 6.80 | 0.90 | 0.70 | ease_in_out | R -65.0, L +65.0 |
| antennas | recover | 8.60 | 1.10 | 0.00 | minjerk | R -10.0, L +10.0 |

**boredom:neutral** — 길이 8.40 s

| 트랙 | 라벨 | 도착 s | duration s | pause s | 보간 | 주요 목표값 |
|---|---|---|---|---|---|---|
| head | look-left | 1.50 | 1.50 | 1.20 | linear | pitch +6.0, yaw +25.0 |
| head | look-right | 5.70 | 3.00 | 1.20 | linear | pitch +6.0, yaw -25.0 |
| head | back | 8.40 | 1.50 | 0.00 | linear | rest(0) |

## 3. Expressive vs Neutral

| 모션 | 계획 같은 시작 / 종료 | 비교 문제 | 길이 E / N s | 측정 시작 차 (각°/이동 mm) | 측정 종료 차 | 기본 동작 일치 (neutral 키 → expressive 키) |
|---|---|---|---|---|---|---|
| boredom | 예 / 예 | 0 | 8.60 / 8.40 | 0.04/0.03 | 0.11/0.10 | ✓ look-left (Δyaw +25.0) → look-left (Δyaw +25.0), sigh (Δyaw +25.0); look-right (Δyaw -50.0) → look-right (Δyaw -50.0); back (Δyaw +25.0) → look-left (Δyaw +25.0), sigh (Δyaw +25.0) |

## 4. 전체 궤적 검사 (계획, computed, 초기 정책)

| 모션 | 판정 | IK NaN | 최소 관절 여유 ° (관절) | Stewart / 몸통 / 안테나 속도 비 | 최대 roll / pitch / 상대 yaw ° | z 범위 mm | 경고 |
|---|---|---|---|---|---|---|---|
| boredom:expressive | 통과 | 0 | 37.2 (stewart_3) | 0.08 / 0.00 / 0.06 | 4.0 / 16.0 / 25.0 | -10.0…0.0 | draft |
| boredom:neutral | 통과 | 0 | 31.3 (stewart_3) | 0.01 / 0.00 / 0.00 | 0.0 / 6.0 / 25.0 | 0.0…0.0 | velocity_step, draft |

## 5. 눈으로 확인하는 재생 명령 (MuJoCo viewer, 127.0.0.1)

```
.venv\Scripts\python -m reachy_motion sim-play boredom --variant expressive
.venv\Scripts\python -m reachy_motion sim-play boredom --variant neutral
```

재생 후 Enter = 다시, r = 파일 다시 읽기(수정 반영), v = 다른 변형, q = 종료.
