# 모션 사양표 (자동 생성 — 직접 고치지 말 것)

생성: `python -m reachy_motion phase2` (2026-11-14 00:38). 원본: `motions/*.yaml`.
모든 모션은 학생이 확정한 설계다(`draft: false`). 실행 파라미터는 계획기(SDK 보간)로 계산한 값(computed)이고, V/A는 설계 목표(예상)다. 정책 판정은 초기 정책(관절 여유 10°, 무부하 속도 50%)이며 기구적 안전 보장이 아니다.

## `aha_recommend:expressive`

- 의도: Aha! I have an idea - try this one (looks at the recommended item on its left).
- 예상 V/A(설계 목표): valence +0.70, arousal +0.60
- 길이 3.50 s, 배율 amplitude ×1, tempo ×1, 효과음 `aha.wav` @ 0.85 s(GUI가 로봇 스피커·노트북으로 재생, motions/sounds/)
- 적용한 애니메이션 원리:
  - **anticipation** — head 'think' (pitch +10, yaw -8, z -2 mm) and antenna 'droop', then a 0.3 s still pause before the pop
  - **timing** — the 0.3 s pause separates thinking from the realization; the 0.55 s pop is the fastest key (speed ratio <= 0.40)
  - **exaggeration** — head 'pop': cartoon easing (+-10 % anticipation / overshoot) up to pitch -15 with z +6 mm
  - **staging** — head and antennas freeze 0.35 s at the top of the pop; 'present' holds 0.6 s on the item (yaw +22, pitch +4)
  - **squash_and_stretch** — the head sinks 2 mm while thinking and rises to z +6 mm on the pop
  - **secondary_action** — antenna 'wiggle' while presenting
  - **follow_through_and_overlapping_action** — the antenna wiggle continues after the head has stopped on the item; antennas settle with the head

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | think | 0.00 | 0.50 | 0.80 | 0.50 | 0.30 | ease_in_out | x_mm=0.0, y_mm=0.0, z_mm=-2.0, roll_deg=4.0, pitch_deg=10.0, yaw_deg=-8.0 | rot deg/s=54, trans mm/s=8 |
| head | 1 | pop | 0.80 | 1.35 | 1.70 | 0.55 | 0.35 | cartoon | x_mm=0.0, y_mm=0.0, z_mm=6.0, roll_deg=0.0, pitch_deg=-15.0, yaw_deg=0.0 | rot deg/s=270, trans mm/s=81 |
| head | 2 | present | 1.70 | 2.20 | 2.80 | 0.50 | 0.60 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=-6.0, pitch_deg=4.0, yaw_deg=22.0 | rot deg/s=110, trans mm/s=22 |
| head | 3 | back | 2.80 | 3.50 | 3.50 | 0.70 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=63 |
| antennas | 0 | droop | 0.00 | 0.50 | 0.80 | 0.50 | 0.30 | minjerk | right_deg=-30.0, left_deg=30.0 | ant deg/s=75 |
| antennas | 1 | perk | 0.80 | 1.35 | 1.70 | 0.55 | 0.35 | cartoon | right_deg=5.0, left_deg=-5.0 | ant deg/s=356 |
| antennas | 2 | wiggle-a | 1.70 | 1.85 | 1.85 | 0.15 | 0.00 | ease_in_out | right_deg=-5.0, left_deg=5.0 | ant deg/s=133 |
| antennas | 3 | wiggle-b | 1.85 | 2.00 | 2.80 | 0.15 | 0.80 | ease_in_out | right_deg=5.0, left_deg=-5.0 | ant deg/s=133 |
| antennas | 4 | settle | 2.80 | 3.50 | 3.50 | 0.70 | 0.00 | minjerk | right_deg=-10.0, left_deg=10.0 | ant deg/s=40 |

정책 판정: **통과** — 최소 관절 여유 24.4°, Stewart 피크 속도 비 0.39, 안테나 피크 속도 비 0.15 (computed)
경고: cartoon_overshoot

## `aha_recommend:neutral`

- 의도: Look at the recommended item on the left, then back (no expression).
- 예상 V/A(설계 목표): valence +0.20, arousal +0.10
- 길이 2.60 s, 배율 amplitude ×1, tempo ×1, 효과음 없음
- 적용한 애니메이션 원리:
  - **timing** — constant speed (LINEAR) with the same angular speed on both keys

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | present | 0.00 | 0.90 | 1.70 | 0.90 | 0.80 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=4.0, yaw_deg=22.0 | rot deg/s=25 |
| head | 1 | back | 1.70 | 2.60 | 2.60 | 0.90 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=25 |

정책 판정: **통과** — 최소 관절 여유 33.8°, Stewart 피크 속도 비 0.02, 안테나 피크 속도 비 0.00 (computed)
경고: velocity_step

## `boredom:expressive`

- 의도: Bored: looks around for something or someone, nothing happens, slumps into a resting posture, then comes back.
- 예상 V/A(설계 목표): valence -0.50, arousal -0.60
- 길이 7.90 s, 배율 amplitude ×1, tempo ×1, 효과음 `boredom.wav` @ 4.9 s(GUI가 로봇 스피커·노트북으로 재생, motions/sounds/)
- 적용한 애니메이션 원리:
  - **staging** — three readable beats (look-left, look-right, slump), each followed by a still pause
  - **timing** — slow sweeps (1.2 s, and 1.8 s for 50 deg) with 0.5 s pauses; the 0.9 s slump hold is the nothing-happened beat
  - **slow_in_slow_out** — minjerk / ease_in_out on every key
  - **follow_through_and_overlapping_action** — antennas sag during the sweep and drop further 0.3 s after the slump starts; they recover last
  - **exaggeration** — the final slump (pitch 20 deg, z -12 mm) is deeper than the starting posture (pitch 8 deg, z -4 mm)

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | settle | 0.00 | 0.70 | 0.90 | 0.70 | 0.20 | ease_in_out | x_mm=0.0, y_mm=0.0, z_mm=-4.0, roll_deg=0.0, pitch_deg=8.0, yaw_deg=0.0 | rot deg/s=23, trans mm/s=11 |
| head | 1 | look-left | 0.90 | 2.10 | 2.60 | 1.20 | 0.50 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=-4.0, roll_deg=2.0, pitch_deg=8.0, yaw_deg=25.0 | rot deg/s=39 |
| head | 2 | look-right | 2.60 | 4.40 | 4.90 | 1.80 | 0.50 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=-4.0, roll_deg=-2.0, pitch_deg=8.0, yaw_deg=-25.0 | rot deg/s=52 |
| head | 3 | slump | 4.90 | 5.90 | 6.80 | 1.00 | 0.90 | ease_in_out | x_mm=0.0, y_mm=0.0, z_mm=-12.0, roll_deg=5.0, pitch_deg=20.0, yaw_deg=0.0 | rot deg/s=54, trans mm/s=16 |
| head | 4 | back | 6.80 | 7.90 | 7.90 | 1.10 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=35, trans mm/s=20 |
| antennas | 0 | wait | 0.00 | 0.20 | 0.20 | 0.20 | 0.00 | minjerk | right_deg=-10.0, left_deg=10.0 |  |
| antennas | 1 | lower | 0.20 | 1.00 | 2.60 | 0.80 | 1.60 | ease_in_out | right_deg=-35.0, left_deg=35.0 | ant deg/s=63 |
| antennas | 2 | sag | 2.60 | 4.40 | 5.20 | 1.80 | 0.80 | ease_in_out | right_deg=-45.0, left_deg=45.0 | ant deg/s=11 |
| antennas | 3 | droop | 5.20 | 6.10 | 6.90 | 0.90 | 0.80 | ease_in_out | right_deg=-75.0, left_deg=75.0 | ant deg/s=67 |
| antennas | 4 | recover | 6.90 | 7.90 | 7.90 | 1.00 | 0.00 | minjerk | right_deg=-10.0, left_deg=10.0 | ant deg/s=122 |

정책 판정: **통과** — 최소 관절 여유 34.8°, Stewart 피크 속도 비 0.09, 안테나 피크 속도 비 0.05 (computed)

## `boredom:neutral`

- 의도: Idle look left, look right and back (no expression).
- 예상 V/A(설계 목표): valence +0.00, arousal -0.30
- 길이 7.70 s, 배율 amplitude ×1, tempo ×1, 효과음 없음
- 적용한 애니메이션 원리:
  - **timing** — constant speed (LINEAR), same angular speed on every key

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | look-left | 0.00 | 1.45 | 2.45 | 1.45 | 1.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=8.0, yaw_deg=25.0 | rot deg/s=18 |
| head | 1 | look-right | 2.45 | 5.25 | 6.25 | 2.80 | 1.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=8.0, yaw_deg=-25.0 | rot deg/s=18 |
| head | 2 | back | 6.25 | 7.70 | 7.70 | 1.45 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=18 |

정책 판정: **통과** — 최소 관절 여유 30.0°, Stewart 피크 속도 비 0.02, 안테나 피크 속도 비 0.00 (computed)
경고: velocity_step

## `success:expressive`

- 의도: Yes! It worked - a happy bounce and nods.
- 예상 V/A(설계 목표): valence +0.80, arousal +0.60
- 길이 2.10 s, 배율 amplitude ×1, tempo ×1, 효과음 `success.wav` @ 0.3 s(GUI가 로봇 스피커·노트북으로 재생, motions/sounds/)
- 적용한 애니메이션 원리:
  - **anticipation** — head 'crouch' (pitch +6, z -5) before the pop
  - **exaggeration** — cartoon 'pop' up with z +5 mm
  - **follow_through_and_overlapping_action** — two damped nods after the pop
  - **secondary_action** — antenna wiggle (+-10 deg) after the perk

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | crouch | 0.00 | 0.30 | 0.30 | 0.30 | 0.00 | ease_in_out | x_mm=0.0, y_mm=0.0, z_mm=-5.0, roll_deg=0.0, pitch_deg=6.0, yaw_deg=0.0 | rot deg/s=40, trans mm/s=33 |
| head | 1 | pop | 0.30 | 0.80 | 0.95 | 0.50 | 0.15 | cartoon | x_mm=0.0, y_mm=0.0, z_mm=5.0, roll_deg=0.0, pitch_deg=-10.0, yaw_deg=0.0 | rot deg/s=179, trans mm/s=112 |
| head | 2 | nod-down | 0.95 | 1.25 | 1.25 | 0.30 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=8.0, yaw_deg=0.0 | rot deg/s=112, trans mm/s=31 |
| head | 3 | nod-up | 1.25 | 1.55 | 1.55 | 0.30 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=-4.0, yaw_deg=0.0 | rot deg/s=75 |
| head | 4 | back | 1.55 | 2.10 | 2.10 | 0.55 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=14 |
| antennas | 0 | wait | 0.00 | 0.30 | 0.30 | 0.30 | 0.00 | minjerk | right_deg=-10.0, left_deg=10.0 |  |
| antennas | 1 | perk | 0.30 | 0.70 | 0.70 | 0.40 | 0.00 | cartoon | right_deg=15.0, left_deg=-15.0 | ant deg/s=350 |
| antennas | 2 | wiggle-a | 0.70 | 0.85 | 0.85 | 0.15 | 0.00 | ease_in_out | right_deg=-5.0, left_deg=5.0 | ant deg/s=267 |
| antennas | 3 | wiggle-b | 0.85 | 1.00 | 1.00 | 0.15 | 0.00 | ease_in_out | right_deg=15.0, left_deg=-15.0 | ant deg/s=267 |
| antennas | 4 | wiggle-c | 1.00 | 1.15 | 1.15 | 0.15 | 0.00 | ease_in_out | right_deg=-5.0, left_deg=5.0 | ant deg/s=267 |
| antennas | 5 | settle | 1.15 | 1.75 | 1.75 | 0.60 | 0.00 | minjerk | right_deg=-10.0, left_deg=10.0 | ant deg/s=16 |

정책 판정: **통과** — 최소 관절 여유 29.4°, Stewart 피크 속도 비 0.37, 안테나 피크 속도 비 0.15 (computed)
경고: cartoon_overshoot

## `success:neutral`

- 의도: Two plain nods (yes), no expression.
- 예상 V/A(설계 목표): valence +0.30, arousal +0.00
- 길이 2.00 s, 배율 amplitude ×1, tempo ×1, 효과음 없음
- 적용한 애니메이션 원리:
  - **timing** — constant speed (LINEAR), 20 deg/s on every key

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | nod-down | 0.00 | 0.50 | 0.50 | 0.50 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=10.0, yaw_deg=0.0 | rot deg/s=20 |
| head | 1 | nod-up | 0.50 | 1.00 | 1.00 | 0.50 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=20 |
| head | 2 | nod-down-2 | 1.00 | 1.50 | 1.50 | 0.50 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=10.0, yaw_deg=0.0 | rot deg/s=20 |
| head | 3 | back | 1.50 | 2.00 | 2.00 | 0.50 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=20 |

정책 판정: **통과** — 최소 관절 여유 37.1°, Stewart 피크 속도 비 0.02, 안테나 피크 속도 비 0.00 (computed)
경고: velocity_step

## `failure:expressive`

- 의도: Oh no - it failed: small flinch, slumps with antennas down, shakes the head, recovers.
- 예상 V/A(설계 목표): valence -0.60, arousal -0.30
- 길이 3.70 s, 배율 amplitude ×1, tempo ×1, 효과음 `failure.wav` @ 0.2 s(GUI가 로봇 스피커·노트북으로 재생, motions/sounds/)
- 적용한 애니메이션 원리:
  - **anticipation** — head 'flinch' (pitch -4, z +3) before the slump
  - **timing** — quick flinch 0.2 s vs slow slump 0.9 s
  - **follow_through_and_overlapping_action** — antenna droop lags the head and recovers after it
  - **secondary_action** — head shake while slumped
  - **exaggeration** — slump with roll tilt and z -8 mm

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | flinch | 0.00 | 0.20 | 0.20 | 0.20 | 0.00 | ease_in_out | x_mm=0.0, y_mm=0.0, z_mm=3.0, roll_deg=0.0, pitch_deg=-4.0, yaw_deg=0.0 | rot deg/s=40, trans mm/s=30 |
| head | 1 | slump | 0.20 | 1.10 | 1.50 | 0.90 | 0.40 | ease_in_out | x_mm=0.0, y_mm=0.0, z_mm=-8.0, roll_deg=-8.0, pitch_deg=18.0, yaw_deg=0.0 | rot deg/s=52, trans mm/s=24 |
| head | 2 | shake-left | 1.50 | 1.85 | 1.85 | 0.35 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=-8.0, roll_deg=-6.0, pitch_deg=16.0, yaw_deg=10.0 | rot deg/s=53 |
| head | 3 | shake-right | 1.85 | 2.20 | 2.20 | 0.35 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=-8.0, roll_deg=-6.0, pitch_deg=16.0, yaw_deg=-10.0 | rot deg/s=107 |
| head | 4 | center | 2.20 | 2.50 | 2.80 | 0.30 | 0.30 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=-8.0, roll_deg=-6.0, pitch_deg=16.0, yaw_deg=0.0 | rot deg/s=63 |
| head | 5 | recover | 2.80 | 3.70 | 3.70 | 0.90 | 0.00 | minjerk | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=36, trans mm/s=17 |
| antennas | 0 | wait | 0.00 | 0.30 | 0.30 | 0.30 | 0.00 | minjerk | right_deg=-10.0, left_deg=10.0 |  |
| antennas | 1 | droop | 0.30 | 1.20 | 2.60 | 0.90 | 1.40 | ease_in_out | right_deg=-80.0, left_deg=80.0 | ant deg/s=156 |
| antennas | 2 | recover | 2.60 | 3.60 | 3.60 | 1.00 | 0.00 | minjerk | right_deg=-10.0, left_deg=10.0 | ant deg/s=131 |

정책 판정: **통과** — 최소 관절 여유 38.0°, Stewart 피크 속도 비 0.10, 안테나 피크 속도 비 0.07 (computed)

## `failure:neutral`

- 의도: Plain head shake (no), no expression.
- 예상 V/A(설계 목표): valence -0.20, arousal +0.00
- 길이 2.00 s, 배율 amplitude ×1, tempo ×1, 효과음 없음
- 적용한 애니메이션 원리:
  - **timing** — constant speed (LINEAR), 24 deg/s on every key

| 트랙 | # | 라벨 | 출발 s | 도착 s | 해제 s | duration s | pause s | 보간 | 목표값 | 공칭 피크 속도 |
|---|---|---|---|---|---|---|---|---|---|---|
| head | 0 | left | 0.00 | 0.50 | 0.50 | 0.50 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=12.0 | rot deg/s=24 |
| head | 1 | right | 0.50 | 1.50 | 1.50 | 1.00 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=-12.0 | rot deg/s=24 |
| head | 2 | center | 1.50 | 2.00 | 2.00 | 0.50 | 0.00 | linear | x_mm=0.0, y_mm=0.0, z_mm=0.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0 | rot deg/s=24 |

정책 판정: **통과** — 최소 관절 여유 40.2°, Stewart 피크 속도 비 0.01, 안테나 피크 속도 비 0.00 (computed)
경고: velocity_step
