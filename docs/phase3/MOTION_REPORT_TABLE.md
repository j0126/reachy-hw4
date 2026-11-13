# 보고서용 모션 표 (2026-11-11 확정본)

과제 보고서가 요구하는 모션별 표(상태·트리거·원리·설정·참고 논문·의도한 읽힘)다. 원본은 확정된 `motions/*.yaml` 8개다
(`draft: false`, 수정 1차).

**값의 성격**
- 설정값은 확정 파일에서 계산한 값이다(computed). 전체 키프레임은 `docs/phase2/MOTION_SPECS.md`에 있다.
- V/A는 **설계 목표**이고 측정값이 아니다. 괄호 안 숫자는 [09]의 0–100 슬라이더 척도로 바꾼 값이다(50 × (값 + 1)).
- 최고 속도는 머리 회전의 공칭 피크(보간 곡선의 최댓값)다. 'Stewart 속도 비'는 가장 바쁜 Stewart 모터의 피크 속도를
  XL330-M288-T 무부하 속도(5 V, 618 °/s)로 나눈 값이다(`docs/phase1/SDK_ANALYSIS.md` §모터).

**아직 확인되지 않은 것**
- 효과음(2026-11-14부터, failure·boredom은 수정 2차): aha E `aha.wav` 0.85 s, success E `success.wav` 0.3 s, failure E `failure.wav` 0.2 s,
  boredom E `boredom.wav` 4.9 s. 직접 합성한 소리(`motions/sounds/`)를 GUI가 실제 로봇 재생 때 로봇 내장 스피커로 낸다(노트북 스피커로
  바꿀 수 있음). Neutral은 소리가 없다. 그래서 네 모션 모두 E와 N은 움직임·안테나·소리가 다르다.
  소리 규칙(V/A 설계 목표에서): valence → 음의 방향·조(긍정 = 올라감·장조, 부정 = 내려감·단조), arousal → 빠르기·높이·크기(aha·success 빠르고 높게 -6 dBFS, failure 느리게 한 옥타브 아래 -8 dBFS, boredom 아주 느리고 낮게 -10 dBFS). 밝기(2 kHz 위 에너지, computed): aha −9 dB, success −2 dB, failure −54 dB, boredom −45 dB.
- 안테나 방향(처짐 = 오른쪽 −, 왼쪽 +)과 roll 부호는 실제 로봇에서 확인하지 않았다(Phase 4).

## 참고 논문

**[06]** L. Takayama, D. Dooley, W. Ju, "Expressing Thought: Improving Robot Readability with Animation Principles,"
HRI 2011, pp. 69–76. doi:10.1145/1957656.1957674.

이 논문에서 쓰는 내용(요약):
- **forethought와 reaction**: 기능 동작 직전에 생각을 보여 주는 것이 forethought, 과제 결과(성공·실패)에 목표 지향적으로
  반응하는 것이 reaction이다. 생각을 보여 줄 때는 행동하기 직전에 표현 동작을 넣고, 돌아설 방향을 먼저 본다(§2.1.4).
- **비교 조건**: forethought·reaction이 없는 조건은 과제에 필요한 **기능 동작만** 보여 줬다(§2.1.1). 우리 neutral의 정의와 같다.
- **동작 단서**:
  - 위로 올라가는 동작은 자신감·긍정, 아래로 내려가는 동작은 자신감 부족·부정으로 썼다(§2.1.3).
  - 성공에는 경쾌한 속도, 실패에는 느리게 처지는 동작을 썼다(§2.1.4).
- **결과** (온라인 영상 실험, N = 273):
  - forethought를 보면 사람들이 자기 해석을 더 확신했고(7점 척도 5.69 대 5.20), 로봇이 더 호감 가고 다가가기 쉽게 보였다.
    다만 키워드로 맞힌 정답률 차이는 유의하지 않았다(§4.1–4.2).
  - reaction은 성공·실패와 관계없이 로봇을 더 유능·지적이고 자신 있게 보이게 했다(§4.3).
- **트리거 설계**: 상위 제어가 다가올 과제를 알면 그 직전에 forethought 동작을, 목표 달성 여부를 알면 그에 맞는 reaction 동작을
  실행하라고 제안한다(§5.1).
- **한계**: 영상 연구이고 여러 요소를 묶어서 시험했다. 저자들은 영상을 한 번만 보게 하라고 권한다(§5.2).

**[09]** A. Rogel, E. Yadollahi, G. Laban, "Emotional Expression in Low-Degrees-of-Freedom Robots: Assessing Perception
with Reachy Mini," arXiv:2605.12786, 2026.

이 논문에서 쓰는 내용(요약):
- **대상과 방법**:
  - Reachy Mini 자체를 대상으로 한 온라인 영상 연구다(N = 100, 약 10 s 클립 10개, 소리 포함).
  - 자극은 Pollen의 감정 생성 모델로 만들었다. Laban 동작 분석을 로봇의 자유도에 대응시켜 V/A 수준을 표현했다(§III-B).
- **측정**(§III-C):
  - 감정 고르기(Geneva Emotion Wheel)
  - V/A 슬라이더(0–100; valence는 부정 → 긍정, arousal은 수동적 → 강렬)
  - 사회적 인상(따뜻함·사교성·생동감)
- **결과**:
  - 정확한 감정 이름은 30.5%만 맞혔다. 넓은 의미는 더 잘 읽혀서, 고른 감정 기준으로 valence 65.9%, arousal 67.8%가 맞았다(§IV-A).
  - 슬픔은 사분면이 98% 맞았다. 그런데 슬라이더로 매긴 arousal은 19%만 '낮음'으로 읽혔다(표 I).
  - 긍정 표현은 더 따뜻하고 사교적으로 평가됐다(§IV-C).
- **관련 연구 인용**: 위로·다가가는 움직임은 긍정 valence, 아래로·멀어지는 움직임은 부정 valence와 연관된다
  (2자유도 로봇 연구, §II).
- **우리가 쓰는 방식**:
  - V/A 목표를 [09]의 사분면(긍정/부정 × 고/저 각성)으로 정한다.
  - 사람 평가를 한다면 [09]처럼 '의도 고르기 + V/A 슬라이더'로 묻는다.
  - 낮은 각성(boredom)은 슬라이더에서 실제보다 높게 읽힐 수 있다는 점을 감안한다.

## A. aha_recommend — 의도: 다음 행동 예고

| 항목 | Expressive | Neutral |
|---|---|---|
| 상태 | A(의도). 카페: 추천 메뉴를 정하고 손님에게 보여 주기 직전(Term Project 계획) | 같음 |
| 트리거 | HW4: 키 입력·스크립트 — `play aha_recommend --variant expressive`(Mock), `sim-play aha_recommend`(MuJoCo, Enter 다시·v 변형 전환), GUI 재생. 실제 로봇: Motion Lab 모션 탭 `▶ 실제 로봇 재생`(클릭 1번 = 1번 실행). Term Project(계획): 추천이 정해지는 이벤트 → `MotionService.play("aha_recommend", "expressive")`, [06] §5.1처럼 기능 동작(추천 제시) 직전에 실행 | 같음(`--variant neutral`) |
| 원리 (강의 용어) | **forethought**(생각 → 깨달음 → 제시), **anticipation**(think 자세, cartoon 예비 동작), **timing**(0.3 s·0.35 s 정지), **exaggeration**(cartoon 오버슈트, 큰 pop), **slow in·slow out**(present·back minjerk). 그 밖(Disney): staging, squash & stretch, secondary action, follow-through | 없음(등속 기준선) |
| 설정 | 3.50 s, 효과음 `aha.wav` 0.85 s(로봇 스피커). 머리: think 0.50 s ease_in_out + 정지 0.30 s(roll 4°, pitch 10°, yaw −8°, z −2 mm) → pop 0.55 s cartoon + 정지 0.35 s(pitch −15°, z +6 mm) → present 0.50 s minjerk + 정지 0.60 s(roll −6°, pitch 4°, yaw 22°) → back 0.70 s minjerk. 머리 최고 속도 54 · 270 · 110 · 63 °/s. 안테나: 처짐 ±30° → 세움 +5/−5°(최고 356 °/s) → 흔들기 ±10° → rest. 최대 회전 23.3°, z −2.8…+6.8 mm, Stewart 속도 비 0.386, 최소 관절 여유 24.4° | 2.60 s. present 0.90 s linear + 정지 0.80 s(pitch 4°, yaw 22°) → back 0.90 s linear. 24.8 °/s 등속, 안테나·소리 없음. Stewart 속도 비 0.020, 여유 33.8° |
| 참고 논문 | [06] forethought: 행동 직전에 생각을 보여 주고 갈 방향을 먼저 본다(§2.1.4); 위로 올라가는 동작 = 자신감·긍정(§2.1.3). [09] 긍정-고각성 사분면 목표; 위로 향하는 움직임 = 긍정 valence(§II 인용) | [06] 통제 조건 = 기능 동작만(§2.1.1) |
| 의도한 읽힘 | "생각하다가 좋은 생각이 났다 → 이걸 추천한다." V +0.7(85) / A +0.6(80) | "왼쪽 물건을 본다." V +0.2(60) / A +0.1(55) |
| 그렇게 읽히게 하는 설계 | 고개 숙임과 처진 안테나(생각) → 빠르게 위로 + 안테나 세움 + 정지(깨달음, 긍정·각성) → 품목 쪽 응시와 머리 기울임(제시). 공통 기능 행동은 '왼쪽 22°, 아래 4° 응시'로 N과 같다 | 같은 응시만 일정한 속도로 |

## B. boredom — 상태·감정: 지루함

| 항목 | Expressive | Neutral |
|---|---|---|
| 상태 | B(상태·감정). 카페: 손님이 없는 대기(Term Project 계획) | 같음 |
| 트리거 | HW4: 키 입력·스크립트(`play boredom ...`, `sim-play boredom`, GUI; 실제 로봇은 모션 탭 `▶ 실제 로봇 재생`). Term Project(계획): 대기 상태에서 일정 시간 손님이 없을 때 → `MotionService.set_idle("boredom", "expressive", after_s=…)`. 손님이 오면 다른 모션이 선점한다(`Priority.IDLE`이 가장 낮음). 대기 시간은 팀이 정한다 | 같음 |
| 원리 (강의 용어) | **timing**(양 끝 0.5 s·처짐 0.9 s 정지, 7.9 s의 느린 전개), **slow in·slow out**(ease_in_out·minjerk), **exaggeration**(마지막 처짐이 가장 깊음), **Laban Effort**(설계 해석: Time = sustained, Space = indirect(두리번), Weight = heavy(처짐)). 그 밖: staging(둘러봄 → 아무도 없음 → 처짐), follow-through | 없음(등속 기준선) |
| 설정 | 7.90 s, 효과음 `boredom.wav` 4.9 s(로봇 스피커, 수정 2차). 머리: settle 0.70 s + 0.20 s(pitch 8°, z −4 mm) → look-left 1.20 s minjerk + 0.50 s(yaw +25°) → look-right 1.80 s minjerk + 0.50 s(yaw −25°) → slump 1.00 s ease_in_out + 0.90 s(roll 5°, pitch 20°, z −12 mm) → back 1.10 s minjerk. 머리 최고 속도 23 · 39 · 52 · 54 · 35 °/s. 안테나: 점점 처짐 ±35° → ±45° → ±75°(rest 대비 최대 65°) → rest. 최대 회전 26.2°, Stewart 속도 비 0.087, 여유 34.8° | 7.70 s. look-left 1.45 s linear + 1.0 s(pitch 8°, yaw +25°) → look-right 2.80 s + 1.0 s(yaw −25°) → back 1.45 s. 18 °/s 등속, 안테나·소리 없음. Stewart 속도 비 0.017, 여유 30.0° |
| 참고 논문 | [09] 부정-저각성 사분면(슬픔과 같은 쪽). 슬픔은 고른 감정으로는 사분면이 잘 맞았지만 슬라이더 arousal은 덜 맞았다 → 평가 때 두 방식 모두 본다. 아래로 향하는 움직임 = 부정 valence(§II 인용). [06] 느리고 아래로 처지는 동작 = 부정·자신감 부족(§2.1.3–2.1.4) | [06] 기능 동작만(§2.1.1) |
| 의도한 읽힘 | "할 일이 없어 지루하다. 누가 오나 둘러봤지만 아무도 없어 축 처진다." V −0.5(25) / A −0.6(20) | "좌우를 둘러본다." V 0.0(50) / A −0.3(35) |
| 그렇게 읽히게 하는 설계 | 느린 스캔(최고 39·52 °/s; 빠르면 호기심으로 읽힘), 긴 정지, 점점 처지는 안테나, 마지막에 가장 깊게 처지는 고개(z −12 mm) | 같은 좌우 보기만 일정한 속도로 |

## C1. success — 반응: 성공

| 항목 | Expressive | Neutral |
|---|---|---|
| 상태 | C(반응). 카페: 주문·작업이 성공했을 때(Term Project 계획) | 같음 |
| 트리거 | HW4: 키 입력·스크립트(`play success ...`, `sim-play success`, GUI; 실제 로봇은 모션 탭 `▶ 실제 로봇 재생`). Term Project(계획): 성공 이벤트 → `MotionService.play("success", "expressive", priority=Priority.REACTION, interrupt=True)`. [06] §5.1처럼 목표 달성 여부를 알게 된 직후에 실행 | 같음 |
| 원리 (강의 용어) | **reaction**(성공에 대한 반응), **anticipation**(웅크림 뒤 pop), **exaggeration**(cartoon pop, 안테나 흔들기), **slow in·slow out**(끄덕임 minjerk). 그 밖: follow-through, secondary action | 없음(등속 기준선) |
| 설정 | 2.10 s, 효과음 `success.wav` 0.30 s(로봇 스피커). 머리: crouch 0.30 s ease_in_out(pitch 6°, z −5 mm) → pop 0.50 s cartoon + 0.15 s(pitch −10°, z +5 mm) → 끄덕임 0.30 s ×2 minjerk(pitch +8° → −4°) → back 0.55 s. 머리 최고 속도 40 · 179 · 113 · 75 · 14 °/s. 안테나: 세움 +15/−15°(최고 350 °/s) → ±20° 흔들기 3번 → rest. 최대 회전 11.6°, z ±6 mm, Stewart 속도 비 0.372, 여유 29.4° | 2.00 s. pitch ±10° 끄덕임 두 번, 0.5 s씩 linear, 20 °/s. 안테나·소리 없음. Stewart 속도 비 0.023, 여유 37.1° |
| 참고 논문 | [06] 성공 reaction은 경쾌한 속도(§2.1.4), 위로 올라가는 동작 = 자신감·긍정(§2.1.3), reaction이 로봇을 유능·자신 있게 보이게 함(§4.3). [09] 긍정-고각성 사분면; 긍정 표현이 더 따뜻·사교적으로 평가됨(§IV-C) | [06] 기능 동작(끄덕임)만 |
| 의도한 읽힘 | "됐다! 신난다." V +0.8(90) / A +0.6(80) | "네(긍정)." V +0.3(65) / A 0.0(50) |
| 그렇게 읽히게 하는 설계 | 웅크렸다가 튀어 오르는 머리(z +10 mm 변화), 빠른 끄덕임, 세운 안테나의 흔들기 | 같은 끄덕임만 일정한 속도로 |

## C2. failure — 반응: 실패

| 항목 | Expressive | Neutral |
|---|---|---|
| 상태 | C(반응). 카페: 주문을 이해하지 못했거나 작업이 실패했을 때(Term Project 계획) | 같음 |
| 트리거 | HW4: 키 입력·스크립트(`play failure ...`, `sim-play failure`, GUI; 실제 로봇은 모션 탭 `▶ 실제 로봇 재생`). Term Project(계획): 실패 이벤트 → `MotionService.play("failure", "expressive", priority=Priority.REACTION, interrupt=True)` | 같음 |
| 원리 (강의 용어) | **reaction**(실패에 대한 반응), **anticipation**(움찔 뒤 처짐), **timing**(처진 채 0.4 s 정지, 느린 회복), **exaggeration**(안테나 70° 처짐), **slow in·slow out**(처짐 ease_in_out). 그 밖: follow-through, secondary action | 없음(등속 기준선) |
| 설정 | 3.70 s, 효과음 `failure.wav` 0.2 s(로봇 스피커, 수정 2차). 머리: flinch 0.20 s(pitch −4°, z +3 mm) → slump 0.90 s ease_in_out + 0.40 s(roll −8°, pitch 18°, z −8 mm) → 도리질 0.35 s ×2 minjerk(yaw +10° → −10°) → center 0.30 s + 0.30 s → recover 0.90 s minjerk. 머리 최고 속도 40 · 52 · 53 · 107 · 63 · 36 °/s. 안테나: 처짐 −80/+80°(rest 대비 70°) 1.4 s 유지 → rest. 최대 회전 20.2°, z −8…+3 mm, Stewart 속도 비 0.096, 여유 38.0° | 2.00 s. 도리질 yaw +12° → −12° → 0, linear 24 °/s. 안테나·소리 없음. Stewart 속도 비 0.014, 여유 40.2° |
| 참고 논문 | [06] 실패 reaction은 느리게 처지는 동작(§2.1.4), 아래로 내려가는 동작 = 자신감 부족·부정(§2.1.3), 실패를 인정하는 반응이 부정적 인상을 줄인다(§5.1). [09] 부정 valence; 부정 표현은 덜 따뜻하게 평가됨(§IV-C); 아래로 향하는 움직임 = 부정 valence(§II 인용) | [06] 기능 동작(도리질)만 |
| 의도한 읽힘 | "아, 안 됐다… (실망)" V −0.6(20) / A −0.3(35) | "아니요(부정)." V −0.2(40) / A 0.0(50) |
| 그렇게 읽히게 하는 설계 | 짧은 움찔 → 고개와 안테나가 함께 처짐 → 고개를 숙인 채 도리질 → 천천히 회복 | 같은 도리질만 일정한 속도로 |

## Neutral 공통 정의

- **과제 조건**: 같은 시작·끝 자세(rest), 등속(LINEAR, 이동 구간마다 같은 각속도), 안테나 움직임·소리 없음.
- **기능 동작만**: [06]의 통제 조건처럼 과제에 필요한 기능 동작만 한다(§2.1.1). forethought·reaction 구간은 expressive에만 있다.
- **기본 동작 포함 검사**: neutral의 기본 동작이 expressive 안에 들어 있는지는 `functional_match`로 확인했다
  (`reachy_motion/sim_review.py:106`).
- **aha의 시간 배치**: 응시 구간이 E와 N에서 다른 시각에 온다. 나란히 놓은 영상에서는 두 응시가 겹치지 않는다(2026-11-11 분석).
  발표·보고서에서 비교 영상을 보여 줄 때 이 점을 함께 설명한다.

## 다시 확인하는 방법

```
.venv\Scripts\python -m reachy_motion check <name> --variant both   # 정책·비교 조건 (computed)
.venv\Scripts\python -m reachy_motion phase2                         # docs/phase2/MOTION_SPECS.md 다시 만들기
```
