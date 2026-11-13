# Phase 3 검토 중 추가: boredom 후보 3종 (2026-11-11)

MuJoCo 검토 피드백: 기존 boredom 초안(E·N 모두)은 로봇 왼쪽(yaw +25°)만 보고 돌아온다. 그래서 후보 3종을 새로 만들었다.

- **scan**: 양쪽을 두리번거린다(손님 찾기, 내 제안).
- **story**: '둘러봄 → 아무 일도 없음 → 축 처짐'의 이야기형(검토 의견).
- **doze**: 졸음형.

기존 `motions/boredom.*.yaml`은 **바꾸지 않았다**. 지금도 라이브러리 기본값이고, 전후 비교에 쓰면 된다.
후보는 모두 `name: boredom`, `draft: true`이고 폴더로 구분한다. `default_library()`는 하위 폴더를 읽지 않으므로
기본 라이브러리(8개)는 그대로다.

## 위치와 사용

| 후보 | 폴더 | 이야기 |
|---|---|---|
| scan | `motions/candidates/boredom_scan/` | 지루하지만 "혹시 손님?" — 한숨 → 천천히 왼쪽 → 천천히 오른쪽 → 가운데서 한숨 → 복귀. 양쪽을 볼 때마다 안테나가 살짝 들썩였다가 다시 처짐 |
| story | `motions/candidates/boredom_story/` | 고개 살짝 숙이고 안테나를 낮춤 → 천천히 왼쪽, 정지 → 천천히 오른쪽, 정지 → (아무도 없음) 더 깊이 축 처져 정지 → 복귀. 안테나는 들썩이지 않고 점점 처짐 |
| doze | `motions/candidates/boredom_doze/` | 고개가 천천히 떨어짐 → 한 번 움찔 → 더 깊이 떨어짐(안테나 ≈ 90° 처짐) → 번쩍 깸(고개가 rest보다 위로, 안테나 바로 섬) → 제자리 |

```
.venv\Scripts\python -m reachy_motion sim-play boredom --dir motions\candidates\boredom_scan
.venv\Scripts\python -m reachy_motion sim-play boredom --dir motions\candidates\boredom_story
.venv\Scripts\python -m reachy_motion sim-play boredom --dir motions\candidates\boredom_doze
.venv\Scripts\python -m reachy_motion sim-play boredom          # 기존 초안 (전후 비교)
```

영상으로 한 번에 보기: `.venv\Scripts\python -m reachy_motion video`를 실행하면 기존 4쌍과 후보 3종의 expressive·neutral을
나란히 렌더링한다. 2026-11-11 결과(MP4)는 `results/phase3_sim/videos/20261111_165837/index.html`이고, 방식은
`docs/phase3/MUJOCO_REVIEW.md` §영상으로 보기에 있다.

재생 후 키:
- `v`: 같은 폴더의 neutral과 비교
- `r`: YAML을 고친 뒤 다시 읽어 재생

편집과 검사:
- 편집: YAML을 직접 고치거나 `gui --dir motions\candidates\boredom_scan`
- 검사: `check boredom --dir motions\candidates\boredom_scan --variant both`

## 키프레임 요약

원본은 YAML이다. 값은 계획값이다(computed). E = expressive, N = neutral, EIO = ease_in_out, MJ = minjerk.

| | scan | story | doze |
|---|---|---|---|
| 길이 E / N | 8.60 / 8.40 s | 10.60 / 10.40 s | 7.05 / 6.80 s |
| E 머리 키 (이동 + 정지, 보간, 자세) | slump 1.0+0.3 EIO (roll 4, pitch 12, z −8) → look-left 1.2+0.7 MJ (3, 6, yaw +25, z −5) → look-right 2.0+0.7 MJ (−3, 6, yaw −25, z −5) → sigh 0.9+0.5 EIO (4, 16, z −10) → back 1.3 MJ | settle 1.0+0.4 EIO (pitch 8, z −4) → look-left 1.4+1.0 MJ (2, 8, yaw +25, z −4) → look-right 2.2+0.8 MJ (−2, 8, yaw −25, z −4) → slump 1.1+1.2 EIO (5, 20, z −12) → back 1.5 MJ | drift-down 1.6+0.3 EIO (3, 10, z −6) → catch 0.4+0.2 EIO (1, 6, z −3) → nod-off 2.0+0.8 EIO (6, 22, z −14) → snap-awake 0.35+0.4 MJ (pitch −6, z +3) → settle 1.0 MJ |
| E 안테나 (오른쪽/왼쪽 °) | −50/+50 → 왼쪽 볼 때 −25/+25 → −55/+55 → 오른쪽 볼 때 −25/+25 → 한숨에 −65/+65 → rest | −35/+35 → 스캔 중 −45/+45 → 축 처짐 0.4 s 뒤 −75/+75 → rest | −45/+45 → 움찔 −35/+35 → −90/+90 → 깰 때 +5/−5 → rest |
| E 머리 최고 속도 (키별 °/s) | 25 · 40 · 47 · 59 · 24 | 16 · 33 · 42 · 49 · 26 | 13 · 22 · 17 · **153** · 11 |
| E 안테나 최고 속도 | 141 °/s | 111 °/s | 712 °/s |
| 예상 V / A (설계 목표, 측정 아님) | −0.3 / −0.4 | −0.5 / −0.6 | −0.3 / −0.7 |
| 적용 원리 | timing, slow in/out, staging, secondary action(안테나 들썩), follow-through | staging(세 박자), timing(긴 정지), slow in/out, follow-through, exaggeration(마지막 처짐이 더 깊음) | timing(느린 처짐 대 빠른 깸), slow in/out, squash & stretch(z), secondary action, follow-through, exaggeration |
| N (LINEAR, 같은 각속도, 안테나·소리 없음) | yaw +25 → −25 → 0 (pitch 6), 17 °/s | yaw +25 → −25 → 0 (pitch 8), 13 °/s, 축 처짐 없음 | pitch +16 → 0, 6.7 °/s |
| 초기 정책 E / N: 최소 관절 여유 · Stewart 속도 비 | 37.2° · 0.08 / 31.3° · 0.02 | 34.8° · 0.08 / 30.0° · 0.01 | 37.0° · 0.31 / 32.7° · 0.01 |

`check` 결과: 6개 모두 초기 정책 안이고, 세 쌍 모두 비교 조건 문제가 0건이다(같은 시작·종료, neutral LINEAR·안테나·소리 없음).
경고는 예상한 것뿐이다(초안 표시, neutral LINEAR 속도 계단). 정책 통과는 기구적 안전 보장이 아니다.

## 설계 메모

- **호기심으로 읽히지 않게**: 좌우 스캔의 최고 속도는 33–47 °/s다. 양 끝에서 0.7–1.0 s 멈추고, 전체 길이는 8.6–10.6 s다.
  참고로 Pollen 녹화 파일에서 계산한 머리 회전 속도의 95번째 백분위수는 boredom1 25 °/s, lonely1(두리번) 61 °/s,
  surprised2 101 °/s다(computed, 우리 측정 아님). 더 지루하게 보이게 하려면 look-left·look-right의 `duration_s`를 늘린다.
- **scan과 story의 핵심 차이**: 안테나의 '들썩'(희망)이 있는지다.
  - scan은 손님을 찾는 idle에 가깝다(A 목표 −0.4).
  - story는 '지루함 → 체념'에 가깝다(A −0.6).
- **doze**: arousal이 가장 낮다. 하지만 카페에서는 꺼짐이나 고장으로 읽힐 위험이 있다. snap-awake 0.35 s가 세 후보 중 가장 빠른
  구간이다(Stewart 속도 비 0.31, 안테나 0.31; 초기 정책 한도 0.5).
- **Neutral 설계**: 기본 동작만 한다. scan·story는 좌우 보기, doze는 내려보기이고, 축 처짐·z 가라앉음·roll 기울임 같은 표현 요소는 뺐다.
  neutral의 키별 회전 변화는 expressive 안에 모두 있다(`functional_match`).
- 안테나 방향(처짐 = 오른쪽 −, 왼쪽 +)과 roll 부호는 실기기에서 검증하지 않았다.

## MuJoCo 확인

로컬 MuJoCo(127.0.0.1:8010, headless)에서 실행했다. 결과는 simulated이고, tick 값은 pc_measured다.
명령은 `sim-verify --dir motions/candidates/boredom_<후보> --out results/phase3_sim/boredom_candidates/<후보>`다.

| 후보 | 결과 폴더 | E / N 실행 | 측정 종료 오차 (rest 대비) | 측정 최소 관절 여유 E / N | E–N 측정 시작·종료 차 | tick |
|---|---|---|---|---|---|---|
| scan | `results/phase3_sim/boredom_candidates/scan/20261111_145945/` | 완료 / 완료 | ≤ 0.10° · 0.10 mm · 안테나 0.01° | 37.1° / 31.3° | 0.04° / 0.11° | 431 / 421, 건너뜀 0, 50.00 Hz |
| story | `…/story/20261111_150025/` | 완료 / 완료 | ≤ 0.09° · 0.10 mm · 0.01° | 34.7° / 30.0° | 0.05° / 0.10° | 531 / 521, 건너뜀 0, 50.00 Hz |
| doze | `…/doze/20261111_150109/` | 완료 / 완료 | ≤ 0.11° · 0.10 mm · 0.01° | 37.3° / 32.8° | 0.15° / 0.20° | 354 / 341, 건너뜀 0, 50.00 Hz |

- 모든 실행은 정지 상태에서 시작했다(측정 시작 오차 ≤ 0.10°).
- 각 쌍에서 neutral의 기본 동작이 expressive 안에 포함된다(`functional_act` 모두 일치).
- 종료 오차는 1 s 유지와 정지 대기 뒤에 쟀다. 움직이는 중의 추종이나 실기기 예측은 아니다.
- 의도가 읽히는지는 눈으로 판단해야 한다(위 `sim-play` 명령).

## 결정 (2026-11-11): story 채택

영상 검토 결과 **story**를 골라 7–8 s로 줄였다. 이제 `motions/boredom.*.yaml`이 story 단축판이다(expressive 7.90 s,
neutral 7.70 s). 바뀐 값과 검사·MuJoCo 결과는 `docs/phase3/MOTION_REVISIONS.md`에 있다.

| 순위 (검토 의견) | 후보 | 판단 |
|---|---|---|
| 1 | story | 이야기 구조가 가장 분명하다(둘러봄 → 아무도 없음 → 처짐). 10.6 s는 길어서 줄였다 |
| 2 | scan | 지루함보다 "누가 있나?" 탐색에 가깝다. Term Project의 Searching 모션 후보 |
| 3 | doze | 졸음(Sleepy)에 가깝다. 손님이 오면 깨는 장면에 쓸 만하다 |
| 4 | 기존 (v0) | 간결하지만 의미가 약하다 |

후보 폴더(`boredom_scan`, `boredom_story`(10.6 s 원본), `boredom_doze`)와 이전 초안 `boredom_v0`은 그대로 둔다.
`video` 명령으로 언제든 다시 비교할 수 있다.

## 모션 출처 (2026-11-11 확인)

- 8개 초안은 Phase 2에서 Claude가 키프레임 값을 직접 작성했다.
  - 생성에 쓴 임시 스크립트 `make_baseline.py`(세션 임시 폴더, 저장소 밖)에는 Pollen·recorded move·HuggingFace 참조가 0건이다.
  - 저장소의 `reachy_motion/`, `motions/`, `tests/`에는 Pollen 감정 라이브러리(`pollen-robotics/reachy-mini-emotions-library`,
    `RecordedMove`) 참조가 없다.
- 후보 3종도 직접 작성했다. Pollen 녹화는 위의 속도 참고값으로만 보았고, 궤적을 가져오지 않았다.
- SDK 1.11.0에는 Pollen 감정 라이브러리를 재생하는 경로가 있다(`reachy_mini/motion/recorded_move.py:25`). 이 저장소는 그 경로를
  쓰지 않는다.
