# 모션 설계 초안 (Phase 2)

HW4 모션 A(aha_recommend)·B(boredom)·C(success / failure) × Expressive / Neutral 8개의 **초기 초안**이다.
교수님 요구에 따라 최종 모션은 학생이 직접 설계·조정한다. 여기 값은 출발점이며 사람이 평가하지 않았다.

**2026-11-11 수정 1차**: aha expressive와 boredom 두 변형을 바꿨다. 아래 표는 현재 값이다. 바뀐 내용과 이유는
[../phase3/MOTION_REVISIONS.md](../phase3/MOTION_REVISIONS.md)에 있고, 이전 값은 `motions/candidates/*_v0/`에 있다.

**2026-11-11 확정**: 학생이 수정 1차를 최종 설계로 확정했다(8개 모두 `draft: false`). 보고서용 표(상태·트리거·원리·설정·
참고 논문·의도한 읽힘)는 [../phase3/MOTION_REPORT_TABLE.md](../phase3/MOTION_REPORT_TABLE.md)에 있다.

- 원본: `motions/<name>.<variant>.yaml` — 도·mm 단위, 키마다 `label`·`duration_s`·`hold_s`(pause)·`easing`·목표값.
  전역 배율 `scale.amplitude`(진폭), `scale.tempo`(속도). 파일을 고친 뒤 다시 읽으면 바로 반영된다.
- 정확한 키프레임 표와 실행 파라미터: [MOTION_SPECS.md](MOTION_SPECS.md) (`python -m reachy_motion phase2`가 자동 생성).
- 편집: YAML을 직접 고친다(확정 뒤에는 팀과 상의하고 새 수정 차수로 기록). GUI(`python -m reachy_motion gui`)는 보기·재생·비교만
  한다(편집기는 2026-11-12에 뺐다).
- 확인: `check <name> --variant both`(정책·비교), `play <name>`(Mock), `sim-play <name> --variant <v>`(MuJoCo viewer;
  Enter = 다시, r = 파일 다시 읽기, v = 다른 변형, q = 종료).

## 공통 규칙

| 항목 | 내용 |
|---|---|
| 부호 | +pitch = 고개 숙임, +yaw = 로봇 왼쪽, roll 부호는 실기기 미확인 |
| 안테나 | `[right, left]` 절대각. rest = −9.998 / +9.998°(SDK ±0.1745 rad). droop(처짐) = right 더 −, left 더 +, perk(세움) = 0° 쪽. **방향은 SDK sleep 자세(−175/+175°)에서 추론, 실기기 미확인** |
| 시작·종료 | 8개 모두 rest 자세에서 시작해 rest로 끝난다(head 0, 안테나 rest, 몸통 0) |
| 정책 | 초기 정책(관절 여유 ≥ 10°, 무부하 속도 ≤ 50%, DOF 포락선) 통과 + 여유 목표(여유 ≥ 15°, 속도 비 ≤ 0.40). **기구적 안전 보장 아님** |
| MuJoCo | Stewart 응답이 마찰 지배적이라 작은·빠른 동작은 둔해 보인다(Phase 1 §5.5). 주 동작 ≥ 8°, 유지 ≥ 0.2 s 권장 |
| 효과음 | expressive만 `sound`(파일·시각). 2026-11-14부터 GUI가 실제 로봇 재생 때 로봇 내장 스피커(또는 노트북)로 낸다. failure·boredom은 수정 2차에서 더했다([../../motions/sounds/README.md](../../motions/sounds/README.md)) |

## Expressive vs Neutral 비교 조건

Neutral = 같은 기능 동작(같은 시선 목표·끄덕임·도리질)을 **일정 속도(LINEAR, 키마다 같은 각속도)·안테나 정지·효과음 없이** 수행.
`library.compare.comparison_conditions`가 검사하며 8개 모두 위반 0건이다(같은 시작·종료 자세 포함).

| 모션 | Expressive (길이·경로·보간·안테나·효과음) | Neutral (길이·경로·속도) |
|---|---|---|
| aha_recommend | 3.50 s: think(+0.3 s 정지) → pop(cartoon, +0.35 s 정지) → present(yaw +22, pitch +4) → back, 안테나 droop → perk(머리와 동시) → wiggle → settle, `aha.wav` | 2.60 s: present → back, LINEAR ≈ 25°/s |
| boredom | 7.90 s: settle → look-left(yaw +25) → look-right(yaw −25) → slump(0.9 s 정지) → back, 안테나 lower → sag → droop(늦게) → recover, `boredom.wav`(수정 2차) | 7.70 s: look-left → look-right → back, LINEAR ≈ 18°/s |
| success | 2.10 s: crouch → pop(cartoon) → nod ×2 → back, 안테나 perk·wiggle, `success.wav` | 2.00 s: 끄덕임 ×2, LINEAR 20°/s |
| failure | 3.70 s: flinch → slump(tilt) → 도리질 → center → recover, 안테나 droop(늦게)·recover, `failure.wav`(수정 2차) | 2.00 s: 도리질 ±12°, LINEAR 24°/s |

## 모션별 설계

예상 V/A는 설계 목표다(측정값 아님). 근거: 머리 들기·안테나 세우기 = 긍정 valence, 숙이기·처짐 = 부정; 속도·진폭·템포 = arousal.

| 모션 | 의도 | 예상 V / A (expr · neut) | 적용 원리 (키 라벨) | 조정 가이드 |
|---|---|---|---|---|
| aha_recommend | "좋은 생각! 이걸 추천해요" — 왼쪽 메뉴를 봄 | +0.7 / +0.6 · +0.2 / +0.1 | anticipation(think + 0.3 s 정지, droop), timing, exaggeration(pop cartoon), staging(pop 0.35 s 정지, present 0.6 s), squash & stretch(z −2 → +6), secondary(wiggle), follow-through | pop duration↓ = arousal↑(속도 비 ≤ 0.40 확인), present yaw로 메뉴 방향 |
| boredom | 둘러봐도 아무도 없어 지루함(idle) | −0.5 / −0.6 · 0.0 / −0.3 | staging(세 박자), timing(느린 스캔·정지), slow-in/out, follow-through(안테나 늦게 처짐), exaggeration(마지막 처짐이 더 깊음) | look-left/right `duration_s`↑ = 더 지루하게(빠르면 호기심), slump pitch·hold로 실망 정도 |
| success | "성공!" 반가운 반응 | +0.8 / +0.6 · +0.3 / 0.0 | anticipation(crouch), exaggeration(pop), follow-through(감쇠 nod), secondary(안테나 wiggle) | wiggle 횟수·폭, pop 높이(z) |
| failure | "아, 실패…" 실망 | −0.6 / −0.3 · −0.2 / 0.0 | anticipation(flinch), timing(빠른 flinch vs 느린 slump), follow-through(안테나 늦은 droop·회복), secondary(도리질), exaggeration(tilt) | slump pitch·roll, droop 각도(−80/+80°) |

계산한 실행 지표(computed, 초기 정책 기준, 수정 1차 반영): 최소 관절 여유 24.4–40.2°(가장 작은 값은 aha expressive),
Stewart 피크 속도 비 ≤ 0.39(aha expressive), 안테나 ≤ 0.18, 몸통 0. 경고는 예상된 것뿐이다: cartoon 외삽(aha·success expressive), LINEAR 속도 계단(neutral 4개), 초안 표시.

## 한계

- 사람 평가 없음: V/A는 목표값. 효과음도 설계 규칙으로만 만들었고 사람이 평가하지 않았다.
- MuJoCo는 실기기보다 낙관적·마찰 지배적이라 속도감이 다르다. 실기기 확인은 최종 설계 확정 후, 별도 승인(Phase 4)으로만.
- 안테나 방향(droop/perk)은 추론, roll 부호는 미확인.
- 초안은 설계 패널(3인 디자이너 + 심사) 대신 기준 초안을 다듬어 만들었다(작업 중단으로 패널 미완료).
