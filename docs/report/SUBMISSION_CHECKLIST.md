# HW4 제출 체크리스트 (2026-11-14 기준)

기준: 교수님 과제 원문 "Homework 4: Expressive Motion on Reachy Mini". 제출 11/16 23:59, 발표 11/17 (HW4 10분 + Term Project 제안 5분).

- 상태: ✅ 됨 · ⚠️ 일부 됨 또는 고칠 것 · ❌ 아직 안 함
- 역할: **개발**(코드·GUI·설명서, 인수인계) · **팀원**(실험·촬영·분석·보고서·발표). 팀원 사용법은 [TEAM_GUIDE.md](../TEAM_GUIDE.md).

## 남은 일 (먼저 할 순서)

| # | 할 일 | 누가 | 볼 곳 |
|---|---|---|---|
| 1 | 실제 로봇 R3 D 사다리: (MuJoCo 먼저) ② 실험 → R3 → D 1.0 → 0.6 → 0.4 → 0.3 → 0.25 → 0.2 s를 한 단계씩 | 팀원 (조작·안전) | TEAM_GUIDE §4.4 |
| 2 | 실제 로봇 R2 Neutral: aha N, boredom N, failure N (Expressive 4개와 success N은 11/13–14에 측정함. 같은 날 E도 다시 재면 비교에 좋다) | 팀원 (조작·안전) | TEAM_GUIDE §4.3 |
| 3 | 1·2를 하면서 휴대폰으로 촬영 (E/N 짝, R3 단계) | 팀원 (촬영) | TEAM_GUIDE §5 |
| 4 | 팀원 이름·학번·기여 | 팀원 | 보고서 맨 위 |
| 5 | 보고서 3.4·3.5 표와 그림, 요약·결론 채우기 (1·2 뒤) | 팀원 (보고서) | TEAM_GUIDE §6–7 |
| 6 | 발표 슬라이드 (구성안 `PRESENTATION_OUTLINE.md` → 슬라이드) | 팀원 (발표) | TEAM_GUIDE §8 |
| 7 | 라이브 시연 리허설 (연결 → Wake-up → 모션 탭 ▶ 실제 로봇 재생) | 팀원 (발표·조작) | TEAM_GUIDE §8 |
| 8 | ✅ 팀원에게 전달: GitHub 저장소 + 인수인계서 (2026-11-14) | 개발 | [HANDOVER.md](../../HANDOVER.md) |
| 9 | 제출 직전: 교수님 제출용 소스 zip 만들기 (`tools/make_submission.py`) | 팀원 (제출) | HANDOVER §8 |

R3 단계 규칙 (GUI가 지킨다, 2026-11-13 변경): 같은 연결 안에서 D 1.0부터 한다. 앞 단계가 진폭비 < 0.8, 지연 보정 RMSE가 진폭의 15% 초과, 오버슈트가 진폭의 15% 초과, 지연(r² ≥ 0.9)이 같은 사다리 D 1.0보다 100 ms 넘게 늘어남, 완료 못 함·S2·S3 정지·오류이면 다음 단계는 거부되고
이유가 로봇 상자와 기록 창에 나온다. 그 단계가 "추종이 무너진 지점"이다. 일정한 지연(약 0.19 s)만으로는 멈추지 않는다. D < 0.2 s는 실제 로봇에서 하지 않는다.
진폭 사다리(선택)는 실제 로봇에서 D ≥ 1 s, A 10°부터 한 단계씩이고 무너지면 더 큰 A가 거부된다(2026-11-13).

## 인수인계 (개발 → 팀원)

| 항목 | 상태 | 위치 |
|---|---|---|
| 설치·실행 (더블클릭) | ✅ Windows / ⚠️ macOS·Linux | Windows `setup_windows.bat`·`run_gui.bat`: 새 복사본에서 설치·`pins OK`·GUI 테스트까지 확인 (2026-11-13, 오프라인 캐시). macOS `setup_mac.command`·`run_gui.command`(Apple Silicon, macOS 14+), Linux `setup_linux.sh`·`run_gui.sh`(Ubuntu 22.04+): 설치 조건만 맞췄고 실제로 실행해 보지 않음 (2026-11-14). [README](../../README.md) §2 |
| 인수인계서 (현황·남은 일·모션 설계 의도·자료 지도·제출 목록·git) | ✅ | [HANDOVER.md](../../HANDOVER.md) |
| 팀원 가이드 (설치 → 실험 → 촬영 → 분석 → 보고서·발표 → 문제 해결) | ✅ | [docs/TEAM_GUIDE.md](../TEAM_GUIDE.md) |
| 보고서 초안·발표 구성안·모션 표를 GUI 실행 경로 기준으로 | ✅ | `HW4_REPORT_DRAFT.md`(3.4.1 실측 결과 추가), `PRESENTATION_OUTLINE.md`, `MOTION_REPORT_TABLE.md` |
| MuJoCo E\|N 영상 (확정 모션 8개) | ✅ | `results/phase3_sim/videos/20261113_214836/` (MP4·WebP, simulated) |
| 이미 잰 실측 기록 (11/12–11/13) | ✅ | `results/lab/2026111[23]_*_robot_*` (TEAM_GUIDE §4.0) |
| 분석 그림 (결과 탭 → `보고서 자료 내보내기`) | ✅ | `main_channel`, `pose`, `joints`, `r1_amplitude`(R1 진폭비), `r3_ladder`(떨림 RMS 포함), `limit_map`(한계 지도), `expressive_vs_neutral` .png + csv |
| 전달 방법 | ✅ | GitHub 저장소 https://github.com/j0126/reachy-hw4 (개발 기록·로그·다시 만들 수 있는 출력은 `.gitignore`로 뺐다). 받은 팀원은 `git clone` → 설치 스크립트 → GUI |

## (1) SDK가 로봇을 움직이는 방법

| 요구사항 | 상태 | 근거·위치 |
|---|---|---|
| `goto_target`이 현재 자세에서 목표까지 duration 동안 보간하는 방법 | ✅ | `docs/phase1/SDK_ANALYSIS.md` §2, 보고서 초안 1.1, 그림 fig5 |
| 보간 4종(linear, minjerk, ease_in_out, cartoon) 차이 + 위치·속도 그래프 | ✅ | `results/phase1/figures/fig1_interpolation_normalized.png`(linear의 시작·끝 속도 계단 설명 2026-11-13 추가), `fig2_interpolation_physical.png` (computed) |
| 머리 자세 6자유도 → Stewart 모터 6개 + 몸통 yaw (IK) | ✅ | SDK_ANALYSIS §4, 보고서 1.3, `fig3_goto_joint_space.png` |
| 새 목표를 보내는 주기 | ✅ | 보고서 1.4 (daemon goto 100 Hz, 제어 루프 50 Hz) |
| 관절 한계 밖 목표는 어떻게 되나 | ✅ | 보고서 1.5 (SDK는 검사하지 않음, IK 실패 → 직전 목표 유지) |
| SDK 소스·공식 문서를 읽은 근거 | ✅ | `docs/phase1/SOURCE_REFERENCES.md` (파일:줄) |

## (2) 표현 모션 설계

| 요구사항 | 상태 | 근거·위치 |
|---|---|---|
| 세 모션: (A) 의도, (B) 상태·감정, (C) 성공·실패 반응, Term Project 시나리오 | ✅ | A aha_recommend, B boredom, C success · failure (`motions/*.yaml` 8개, 2026-11-11 확정) |
| 모션마다 강의 원리 2개 이상 | ✅ | 강의 목록과 겹치는 것: aha = anticipation·timing·exaggeration, boredom = timing·slow in/out·exaggeration, success = anticipation·exaggeration, failure = anticipation·timing·exaggeration. forethought·reaction은 참고 논문 칸에 있다 |
| 실제 설정값(duration, amplitude, peak speed, pause, interpolation)을 코드에 기록 | ✅ | YAML + `docs/phase2/MOTION_SPECS.md` (공칭 피크 속도 포함, computed) |
| Neutral 버전: 같은 시작·끝 자세, 일정 속도, 안테나·소리 없음 | ✅ | `motions/*.neutral.yaml` 4개, `check <모션> --variant both` 비교 조건. 2026-11-14 다시 계산: 4쌍 모두 시작·끝 차이 0, 한 가지 속도(linear), 안테나 키 0개, 소리 없음, 검사기 문제 0건 |
| (선택) Expressive 효과음 | ✅ | Expressive 4개(failure·boredom은 2026-11-14 모션 수정 2차), 로봇 내장 스피커(`motions/sounds/`, GUI `효과음`). 실제 로봇 스피커에서 4개 모두 재생됨을 사람이 들어서 확인 (2026-11-14, 재생 요청 71–90 ms). 사람 평가는 없음 |
| 의도한 읽힘, valence·arousal(논문 09), 그것을 만드는 설계 선택 | ✅ | `docs/phase2/MOTION_DESIGN.md`, `docs/phase3/MOTION_REPORT_TABLE.md` |

## (3) 물리 한계

| 요구사항 | 상태 | 근거·위치 / 남은 일 |
|---|---|---|
| '불가능한 모션' 정의: 관절 한계 밖 자세, 모터가 못 내는 속도·가속 | ✅ | 보고서 3.1 |
| XL330 사양(e-manual)과 기구학으로 한계 추정 (자세에 필요한 모터 속도·가속) | ✅ | 보고서 3.2 표: 속도 비와 관절 최대 가속 (computed) |
| MuJoCo 먼저 | ✅ | R3 D 1.0·0.6·0.4·0.3 s (`results/lab/20261111_222226_sim_R3`, `20261111_234130_sim_R3`, simulated) |
| 실제 로봇에서 한 모션의 D를 단계적으로 줄이기 | ⚠️ | 11/13 22:46: D 1.0 → 0.6 → 0.4 (모두 기준 안, `20261113_224640_robot_R3`). 남은 일 #1: D 0.3 → 0.25 → 0.2 |
| (진폭을 단계적으로 키우기) | ❌ 선택 | A 사다리 미실행. GUI 규칙 준비됨(D ≥ 1 s에서 A 10°부터 한 단계씩, 무너지면 큰 A 거부). D 사다리 뒤 시간이 되면 |
| 명령과 측정 기록 (`get_current_head_pose`, `get_current_joint_positions`) | ✅ | `backends/sdk.py:548-549`, 시행마다 `commands.csv`·`present_measured.csv` |
| 추종이 무너지는 지점 찾기 (lag, overshoot, clipping, shaking, motor error) | ⚠️ | 수치로 보는 것: 지연, 오버슈트, 진폭비(clipping), 정지 중 떨림 RMS(shaking, 2026-11-13 추가; 11/13 0.009–0.014° = 센서 수준). motor error는 허용 GET으로 못 읽어 완료 못 함·S2·S3·오류와 사람 관찰(LED·소리·열). 찾은 것 (measured): 2° 명령은 거의 안 움직임(데드밴드, `R1 진폭비` 그림), 정상 상태 오차, 지연 약 190 ms (보고서 3.4.1). D를 줄였을 때 무너지는 지점은 아직 (#1) |
| 세 표현 모션이 찾은 한계 안인지 | ⚠️ | 그림 준비됨: 결과 탭 `한계 지도`(모션 8개와 R3 단계를 같은 속도·가속 축에, 실제 로봇 실행·무너진 단계 표시). 실제 로봇 R2: Expressive 4개 모두(aha 6회 진폭비 0.97–1.07, boredom 3회 0.87–0.89, success 3회 0.91, failure 2회 1.14)와 success N 1회(0.98). 남은 일 #2(Neutral 3개), 보고서 표 3.5a |
| 안전: sim 먼저, 작고 느리게, 한 번에 한 설정, 첫 이상에서 멈춤, 로봇 무손상 반납 | ✅ / 팀원 | 절차·정지(S1/S2/S3)·R3 단계 거부는 코드에 있다. 현장 안전과 반납은 팀원 (TEAM_GUIDE §2) |

## 발표 (10분)

| 요구사항 | 상태 | 남은 일 |
|---|---|---|
| SDK, 모션 설계·의도한 읽힘, 찾은 한계(무너진 모션 포함) 설명 | ⚠️ | 구성안 `PRESENTATION_OUTLINE.md` (GUI 기준으로 갱신됨). 슬라이드 (#6), 무너진 모션은 #1 뒤 |
| 로봇을 가져와 라이브 시연 (강력 권장) | ⚠️ | 경로는 준비됨: 연결·Wake-up 한 번 뒤 모션 탭 ▶ 실제 로봇 재생 (모션당 클릭 1번, 안테나는 설계대로). 리허설 (#7) |
| 백업 영상 | ⚠️ | MuJoCo E\|N 영상 있음 (`results/phase3_sim/videos/20261113_214836/`, simulated). 실제 로봇 영상 촬영 (#3) |
| 바로 뒤 Term Project 제안 5분 | — | HW4 범위 밖, 별도 준비 |

## 보고서·제출물 (11/16 23:59)

| 요구사항 | 상태 | 남은 일 |
|---|---|---|
| 짧은 보고서 (한국어 가능) | ⚠️ | 초안 `docs/report/HW4_REPORT_DRAFT.md`: 1·2절 거의 완성, 3.4.1 실측 결과 있음, 3.4 표·3.5 표·요약·결론 빈칸 (#5) |
| 팀원 이름·학번·개인 기여 | ❌ | 빈 표 (#4) |
| SDK 설명 | ✅ | 초안 1절 |
| 모션별 표 (상태, 트리거, 원리, 설정, 참고 논문, 의도한 읽힘) | ⚠️ | `MOTION_REPORT_TABLE.md`에 다 있다(트리거 = GUI 버튼으로 갱신). 보고서 2.2로 옮긴다 (#5) |
| 한계 추정과 시험 결과 | ⚠️ | 추정 ✅, 작은 명령·지연 실측 ✅, D 사다리·R2 짝 ❌ (#1, #2, #5) |
| 소스 코드 + 설치·실행 방법 | ✅ | README(Windows·macOS·Linux), 더블클릭 스크립트. 제출 zip은 `tools/make_submission.py`로 만든다 (#9, 들어가는 파일: HANDOVER §8) |
| 짧은 시연 영상 (Expressive·Neutral, 한계 시험) | ❌ | 실제 로봇 촬영 (#3) |
