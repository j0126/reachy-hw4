# Phase 3 모션 수정 1차 (2026-11-11)

**근거**: 사용자가 MuJoCo 영상 7개를 보고 낸 검토 의견이다(시각 검토, simulated; 사람 평가 아님).
- aha: 방향은 좋다. 깨달음의 순간을 더 강조한다.
- boredom: 4개 중 Story를 고르고 7–8 s로 줄인다.
- success·failure: 그대로 쓴다.

이전 버전은 전후 비교용으로 `motions/candidates/aha_v0/`, `motions/candidates/boredom_v0/`에 그대로 남겨 두었다.

## 바뀐 것

| 모션 | 이전 (v0) | 수정 1차 (`motions/<name>.<variant>.yaml`) | 이유 |
|---|---|---|---|
| aha E | 3.05 s, 효과음 0.65 s. think 0.45 s (pitch +6, yaw −8) + 정지 0.15 s → pop 0.45 s cartoon (pitch −12, z +5) + 0.2 s. 안테나 perk는 머리보다 50 ms 늦게 시작 | 3.50 s, 효과음 0.85 s. think 0.5 s (pitch +10, yaw −8, z −2) + **정지 0.3 s** → pop 0.55 s cartoon (pitch −15, z +6) + **정지 0.35 s**. 안테나 perk는 머리와 **같은 순간** 시작해 정지 동안 세운 채 유지 | '생각 중'과 '깨달음'을 분리하고, 느낌표 순간을 따로 보이게 한다 |
| aha N | 2.60 s, 변경 없음 | 〃 | — |
| boredom E | 6.40 s: slump → glance-away (왼쪽 yaw +25만) → sigh → back | Story 후보 채택, **7.90 s**: settle → look-left → look-right → slump (0.9 s 정지) → back. 후보의 10.6 s에서 키와 정지를 줄였고 자세·박자는 그대로다 | 둘러봄 → 아무도 없음 → 축 처짐의 이야기 구조. 좌우를 모두 본다 |
| boredom N | 6.00 s: 왼쪽 보고 복귀, 13 °/s | 7.70 s: 왼쪽 → 오른쪽 → 가운데, LINEAR 18 °/s, 안테나·소리 없음 | 새 expressive의 기본 동작(좌우 보기)과 맞춤 |
| success, failure | 변경 없음 | 〃 | 검토에서 유지하기로 함 |

- **aha pop 값을 고른 과정**: pop을 0.5 s (pitch −16, z +7)로 하면 Stewart 속도 비가 0.46이 되어 Phase 2 여유 목표(≤ 0.40)를 넘었다.
  0.55 s·pitch −15·z +6으로 조정했다. 그래도 머리를 드는 폭은 25°로 v0(18°)보다 크다.
- **boredom 단축 방법**: 좌우 스캔은 느리게 유지했다(최고 39·52 °/s, 양 끝 0.5 s 정지). 정지 시간과 settle·back을 줄였다.
  검토 의견대로 빠른 스캔은 호기심으로 읽힐 수 있어서다.

## 검사 (computed, 초기 정책 + Phase 2 여유 목표)

| | 길이 | 최소 관절 여유 | Stewart 속도 비 | 안테나 속도 비 | 머리 최고 속도 (키별 °/s) | E–N 비교 |
|---|---|---|---|---|---|---|
| aha E | 3.50 s | 24.4° | 0.386 | 0.151 | think 54 · pop 270 · present 110 · back 63 | 문제 0 |
| aha N | 2.60 s | 33.8° | 0.020 | 0 | 25 | |
| boredom E | 7.90 s | 34.8° | 0.087 | 0.053 | settle 23 · look-left 39 · look-right 52 · slump 54 · back 35 | 문제 0 |
| boredom N | 7.70 s | 30.0° | 0.017 | 0 | 18 | |

- 4개 모두 초기 정책(관절 여유 ≥ 10°, 속도 비 ≤ 0.5) 안이고, Phase 2 여유 목표(관절 여유 ≥ 15°, 속도 비 ≤ 0.40)도 만족한다.
- 경고는 예상한 것뿐이다: cartoon 외삽, neutral LINEAR 속도 계단, 초안 표시.
- neutral의 기본 동작은 expressive 안에 포함된다(`functional_match`).
- 정책 통과는 기구적 안전 보장이 아니다.

## MuJoCo 확인 (simulated)

`sim-verify --port 8010`(daemon 경로)으로 수정 1차 8개를 한 세션에서 다시 실행했다. 결과는
`results/phase3_sim/review/20261111_171914/`이다.

| 모션 | 실행 E / N | 측정 종료 오차 | 측정 최소 관절 여유 E / N | E–N 측정 시작·종료 차 |
|---|---|---|---|---|
| aha_recommend | 완료 / 완료 | ≤ 0.10° · 0.10 mm · 안테나 0.01° | 27.0° / 34.0° | 0.10° / 0.04° |
| boredom | 완료 / 완료 | 〃 | 34.8° / 30.1° | 0.03° / 0.10° |
| success (변경 없음) | 완료 / 완료 | 〃 | 31.9° / 39.4° | 0.12° / 0.21° |
| failure (변경 없음) | 완료 / 완료 | 〃 | 39.7° / 41.2° | 0.00° / 0.10° |

- 측정 시작 오차는 ≤ 0.10°였다.
- tick은 건너뜀 0, 49.99–50.00 Hz다(pc_measured).
- 네 쌍 모두 비교 문제가 0이고, neutral의 기본 동작이 expressive 안에 포함된다.

**영상**: `results/phase3_sim/videos/20261111_172236/index.html`, MP4 9개.
- 수정본: `aha_recommend`, `boredom`, `success`, `failure`
- 이전 버전: `aha_v0`, `boredom_v0`
- 후보: `boredom_scan`, `boredom_story`, `boredom_doze`

전후 비교는 `aha_v0` ↔ `aha_recommend`, `boredom_v0` ↔ `boredom`으로 하면 된다. 프레임으로 확인한 것:
- aha: think 정지(t 0.74 s)에서 고개를 숙이고 안테나가 처져 있다. pop 정지(t 1.50 s)에서 머리를 들고 양쪽 안테나가 곧게 선다.
- boredom: look-right(t 3.18 s)에서 오른쪽을 보고, slump 정지(t 6.30 s)에서 축 처진다.

Phase 2 사양표 `docs/phase2/MOTION_SPECS.md`와 `results/phase2/`의 계산 결과물은 `phase2` 명령으로 새 값에 맞춰 다시 만들었다.

## 남은 결정과 주의

- **설계 확정 (2026-11-11)**: 학생이 수정 1차를 최종 설계로 확정했다. `motions/*.yaml` 8개가 `draft: false`이고,
  후보 폴더(`motions/candidates/*`)는 초안 그대로다. 이후 바꾸면 새 수정 차수로 기록한다. 확정 뒤 다시 만든 Phase 2 사양표에는
  초안 경고(`draft`)가 없다. 보고서용 표는 `docs/phase3/MOTION_REPORT_TABLE.md`에 있다.
- **사람 평가를 한다면** (검토 의견): 이름과 조건이 보이지 않는 영상을 쓴다. 무작위 순서로 보여 주고, 참가자가 의도를 먼저
  고른 뒤 V/A를 평가하게 한다. 지금 `video` 영상에는 모션 이름, EXPRESSIVE/NEUTRAL, 키 이름이 찍혀 있어 평가용으로 그대로 쓰면 안 된다.
- **실기기**: 안테나 방향, roll 부호, sim과의 속도·지연 차이는 Phase 4에서만 확인한다(별도 승인, 사용자가 쓴 승인 파일 필요).
- **후보 활용** (Term Project, 검토 의견): scan은 손님을 찾는 Searching 모션, doze는 졸다가 손님을 보고 깨는 모션으로 쓸 수 있다.

## 수정 2차 (2026-11-14): 효과음만 추가

사용자 결정 "둘 다 넣기". 움직임(머리·안테나·몸통 키, 시간, 보간)은 **그대로**이고, 효과음 큐만 더했다.

| 모션 | 수정 1차 | 수정 2차 | 이유 |
|---|---|---|---|
| failure E | 효과음 없음 | `failure.wav` @ 0.2 s (고개를 떨구기 시작할 때): 내려가는 단조 두 음 "어-어", 0.75 s, 조금 작게 | 슬픔은 소리로 가장 잘 전달됐다(Löffler 외, HRI 2018). 긍정 모션에만 소리가 있던 비대칭을 없앰 |
| boredom E | 효과음 없음 | `boredom.wav` @ 4.9 s (처지기 시작할 때): 한숨 같은 낮은 소리, 1.1 s, 아주 작게 | 같은 이유. 카페에서 반복될 수 있어 아주 작게(텀 프로젝트에서는 끌 수 있음) |

- 소리 규칙은 V/A 설계 목표에서 정했다: valence → 음의 방향·조, arousal → 빠르기·높이·크기. aha·success(이미 있던 소리)는 밝게 올라가고,
  failure·boredom은 낮게 내려간다. 음원은 직접 합성했다(`reachy_motion/sound.py`, `motions/sounds/README.md`).
- 이제 네 모션 모두 Expressive와 Neutral이 움직임·안테나·소리에서 다르다. Neutral 4개는 그대로(소리 없음).
- spec 다이제스트가 바뀌었다(효과음이 spec에 들어감): boredom E `50a1f4420cd9` → `c0e95dc1d773`, failure E `0ac84d919ca2` → `a9da1d28103e`.
  움직임이 같으므로 실행 타임라인과 계산 검사 결과(속도 비·관절 여유)는 그대로다. 그 전의 실기기 기록은 옛 다이제스트로 남는다.
- `phase2` 명령으로 `docs/phase2/MOTION_SPECS.md`와 `results/phase2/`를 다시 만들었다(computed).
