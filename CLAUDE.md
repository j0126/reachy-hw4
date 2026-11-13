# CLAUDE.md — Reachy Mini HW4 (Expressive Motion)

DGIST HRI HW4: Reachy Mini Wireless 표현적 모션(A: Aha! 추천 / B: Boredom / C: Success·Failure)의
설계·실행·안전검사·추종성능 분석. 모션 라이브러리는 이후 **Reachy Café Term Project FSM**에서 재사용한다.
패키지: `reachy_motion` (repo root), Python 3.12, venv `.venv` (uv).

## 절대 규칙 (사용자 지시, 예외 없음)

1. **HW3 수정 금지** — `../reachy_hw3`는 읽기 전용 참고 자료. 재사용 코드는 이 repo로 복사하고 출처를 주석으로 남긴다.
   HW3 venv의 Python도 실행하지 않는다(.pyc 생성 방지). 기준선: HEAD `0d49b6b`, 모든 파일 mtime ≤ 2026-10-17.
   HW3에서 `git` 명령(특히 `status`)을 쓰지 않는다 — 임시 `index.lock` 때문에 `.git` 디렉터리 mtime이 바뀐다(2026-11-10 13:33에
   실제로 발생, 파일 내용 변경은 없음). 변경 여부는 `find ../reachy_hw3 -newermt '2026-10-17 09:00'`로만 확인하고, 기대 출력은
   `../reachy_hw3/.git` 한 줄(그 디렉터리 mtime 2026-11-10 13:33:28)뿐이다. HEAD는 파일로 읽는다(`.git/refs/heads/main` = `0d49b6b…`).
2. **SDK/daemon 버전 고정** — `reachy-mini==1.11.0`, `reachy-mini-rust-kinematics==1.0.3`,
   `reachy-mini-motor-controller==1.5.6`. 업그레이드·다운그레이드·재설치 금지. 로봇 쪽 daemon 업데이트도 하지 않는다.
   `python -m reachy_motion env` 가 `pins OK`를 출력해야 하고 `tests/test_sdk_env.py`가 이를 강제한다.
3. **AI 에이전트의 실기기 모터 구동 금지 — 사용자가 GUI에서 직접 확인·승인한 모터 동작만 허용** (2026-11-12 사용자 결정으로 개정).
   - **에이전트(Claude)는 하지 않는다**: 로봇 daemon(`192.168.0.15` — 2026-11-11 사용자 확인, `reachy_motion/settings.py`
     `ROBOT_HOST` — 와 `reachy-mini.local`)에 대한 `ReachyMini(...)` 생성(생성자가 데몬 전역 `SetAutomaticBodyYawCmd`를 보내고
     `media_backend="no_media"`면 daemon 미디어를 해제하므로 그 자체가 상태 변경), `enable_motors`, `goto_target`, `set_target`,
     `wake_up`, `goto_sleep`, `play_move`/upload move, 토크·중력보상·모터 모드 변경, REST `POST /api/move/*`, `/api/motors/*` 등
     상태를 바꾸는 모든 호출, daemon 기동·정지·재시작(`POST /api/daemon/start|stop|restart` — 옵션에 따라 wake_up·reset_to_sleep 실행,
     EEPROM 재기록: 모터 동작). 승인 파일·GUI 승인을 만들거나 고치지 않고, 확인 입력(TTY 승인 ID, GUI '승인' 버튼)을 대신하지 않으며,
     GUI의 실기기 버튼(연결·Wake-up·시행·토크 OFF)을 누르거나 화면 제어로 조작하지 않고, GUI·CLI를 실기기 대상으로 실행하지 않는다.
     원시 버스 통로 `/api/move/ws/raw/write`·`write_raw_packet`은 모든 제한을 우회하므로 누구도 쓰지 않는다.
   - **사람(사용자)의 실기기 실행 경로**:
     (a) Motion Lab GUI(주 경로): 사람이 로봇 상자의 버튼을 눌러 실행한다 — 연결·Wake-up·시행·토크 OFF가 각각 사람의
         클릭 1번이며 그 클릭이 승인이다(별도 승인 창·확인 코드 없음, 2026-11-12 사용자 결정). 시행은 표의 정책 검사를 통과한 것만,
         로봇에서는 한 번에 1개(배치·자동 다음 단계·자동 복귀 없음). 모션 탭의 `▶ 실제 로봇 재생`도 보이는 모션 파일의 R2 시행 1개다
         (같은 정책 검사·클릭 승인·기록, 2026-11-12 사용자 제안). 내부적으로 그 시행의 타임라인 다이제스트에 묶여 1회만 실행된다
         (`safety/gui_approval.py`, `GUI_APPROVAL_ENABLED=True`). 토크 OFF 로봇에서의 연결은 토크를 켠다(`enable_motors`).
         효과음(2026-11-14 사용자 결정 "로봇 스피커로"): 효과음 큐가 있는 R2 시행(Expressive 4개, Neutral은 소리 없음)을 효과음 출력 '로봇
         스피커'로 실행하면 같은 클릭으로 `GET /api/media/status`, `POST /api/media/sounds/upload`(연결마다 파일당 한 번),
         `POST /api/media/play_sound`(큐 시각)도 보낸다(`reachy_motion/sound.py`; 흔들림은 연결 때 꺼 소리가 머리를 움직이지
         않음). 효과음 기본값은 끔이고 GUI `main()`만 로봇 스피커로 켠다. 에이전트는 이 요청들도 보내지 않는다(GET 포함).
         docs/lab/GUI_ROBOT.md.
     (b) CLI(디버깅·비상용): 사용자가 직접 작성한 승인 파일(`safety/approval.py`: 단계·호스트·만료·모션·타임라인 다이제스트·한도) +
         TTY에서 승인 ID 입력. `approval-template`은 출력만 한다.
     같은 로봇을 GUI와 CLI·대시보드·다른 클라이언트로 동시에 제어하지 않는다(SDK에 제어 잠금이 없다). GUI 입력은 UI 자동화로
     대신될 수 있으므로 에이전트 금지 사항은 코드가 아니라 이 규칙으로 지킨다.
   - **코드 상태**: `GUI_APPROVAL_ENABLED=True`, `robot_r1.ROBOT_RUN_ENABLED=True`, `SdkBackend.connect()`가 연결 순서
     (`_connect_robot`: 승인 재확인 → R0 GET → `backends/robot_connect.py` → 승인 재확인)를 실행한다. 테스트는 네트워크 없이
     오프라인 하네스·스텁으로만 이 경로를 검증한다.
   - **에이전트에게 허용(승인 없이)**: REST **GET**만 — `/api/daemon/status`, `/api/kinematics/info`, `/api/state/full`(기본 쿼리만),
     `/api/state/present_head_pose`, `/api/state/present_body_yaw`, `/api/motors/status`, 그리고 쿼리 하나
     `/api/state/full?with_head_joints=true`(2026-11-11 사용자 추가: 컨트롤러가 캐시한 관절값만 읽음, `robot/backend.py:480-506`;
     정확히 이 문자열만, 다른 쿼리와 섞지 않는다). `with_doa=true`와 `/api/state/doa`는 읽기라도
     DoA 폴러 수요를 등록하므로 제외(`daemon/backend/abstract.py:1553-1566`). 모터 레지스터를 읽는 REST 경로는 없다.
4. **기본 실행 환경은 Mock 또는 MuJoCo** — sim daemon은 `reachy_motion.backends.sim_daemon.SimDaemon`으로만 띄우고(127.0.0.1,
   `robot_name=hw4_sim`), 클라이언트는 `ReachyMini(robot_name="hw4_sim", host="127.0.0.1", connection_mode="localhost_only",
   spawn_daemon=False, media_backend="no_media")`. 모션 명령 전 `assert_local_sim(get_status())`로 `simulation_enabled=True`·버전·이름을
   확인하고, 연결 뒤 `assert_motion_client_is_local_sim(mini)`로 **모션 소켓에서도** 같은 확인을 한다 — 이름이 기본값이 아니면
   `localhost_only`는 `host`를 무시하고 "localhost"로 접속하며(`reachy_mini.py:471-476`) 이 PC에서는 ::1이 먼저다. 생성자 자체가
   명령을 보내므로 생성 전에 [::1]:port가 비어 있는지도 확인한다(`run_sim_smoke` 참고).
   기본값 `connection_mode="auto"`는 localhost가 없으면 **조용히 `reachy-mini.local`(실기기)로 넘어가므로 절대 쓰지 않는다**
   (`reachy_mini.py:530-555`).
5. **확인되지 않은 SDK API 사용 금지** — 설치된 1.11.0 소스(`.venv/Lib/site-packages/reachy_mini/…`)에서 확인한 것만 쓴다.
   SDK 동작에 의존하는 코드·문서에는 `파일:줄` 근거를 남긴다(site-packages 기준 상대 경로).
6. **측정하지 않은 데이터를 결과로 제시하지 않는다** — 모든 결과물에 `data_kind`를 표기한다:
   `computed`(SDK 함수 계산) / `mock`(Mock 백엔드의 합성 모델 출력) / `pc_measured`(이 PC에서 실측한 실행기 타이밍 등, 로봇 아님) /
   `simulated`(MuJoCo) / `measured`(실기기). 그림 제목·manifest·보고서 모두. 모션의 V/A 값은 **설계 목표(예상)**이지 측정값이 아니다.
7. **단계마다 테스트하고 기록** — `python -m unittest discover -s tests -t .` 통과 + `docs/VERIFICATION.md`에 결과 기록 후에만 완료로 본다.
8. **단계 진행은 사용자가 정한다** — Phase 2 결과를 사용자가 검토하기 전에는 Phase 3·4로 넘어가지 않는다. 학생의 최종 모션 설계가
   확정되기 전에는 실기기 물리적 한계 실험을 하지 않는다. `motions/*.yaml` 8개는 **2026-11-11 학생이 수정 1차를 확정**했다
   (`draft: false`). 바꾸는 것은 학생이 정하고 새 수정 차수로 기록한다. **수정 2차(2026-11-14, 사용자 결정 "둘 다 넣기")**: boredom·failure
   Expressive에 효과음 큐만 추가(움직임 그대로, docs/phase3/MOTION_REVISIONS.md). **수정 3차(2026-11-14, 사용자 결정
   "±10°로 맞추기")**: failure Neutral 도리질 ±12° → ±10°(E와 같은 폭, 20 °/s, 길이 2.0 s 그대로). `motions/candidates/*`는 초안(`draft: true`) 그대로다.
   관절 여유 10°·무부하 속도 50%는 초기 정책일 뿐 기구적 안전을 보장하지 않는다(보고서·GUI에 그렇게 표시).

## 명령

```
# 설치 (uv 캐시에서 오프라인, constraints.txt = 이 venv의 전체 버전 고정본; HW3 venv는 건드리지 않는다)
uv venv --python 3.12 .venv
uv pip install --offline --python .venv/Scripts/python.exe -c constraints.txt "reachy-mini[mujoco]==1.11.0" matplotlib
uv pip install --offline --no-deps --python .venv/Scripts/python.exe -e .
uv pip install --offline --no-deps --python .venv/Scripts/python.exe av==19.0.1   # 선택: video 명령의 MP4(H.264) 인코더

.venv\Scripts\python -m reachy_motion env        # 버전·핀 확인
.venv\Scripts\python -m reachy_motion phase1     # Phase 1 그래프·표 재생성 (results/phase1, computed)
.venv\Scripts\python -m reachy_motion sim-smoke  # 로컬 MuJoCo goto 확인 (simulated; 127.0.0.1, simulation_enabled 확인 후에만 모션)
.venv\Scripts\python -m reachy_motion sim-api-check  # 로컬 sim에 읽기 전용 REST 점검
.venv\Scripts\python -m unittest discover -s tests -t .
.venv\Scripts\python -m reachy_motion gui             # Reachy HW4 Motion Lab: ① 모션 / ② 실험(R1–R3) / ③ 결과 세 탭(편집기·처음 화면·모드 없음, 2026-11-12 정리), E/N 나란히 영상(오프라인 MuJoCo, 별도 프로세스 → results/lab/videos/), MuJoCo(127.0.0.1:8017; Mock은 테스트 전용으로 숨김), 탭 위 로봇 상자(제목 '실제 로봇'; IP·포트·연결·Wake-up·토크 OFF·연결 끊기, 버튼 클릭 = 승인; 처음부터 보임, 오른쪽 위 `로봇 상자`로 숨기기·다시 열기, 연결 중·실험 탭 백엔드 '실제 로봇'이면 숨길 수 없음; 사용자가 직접 조작, 규칙 3, docs/lab/GUI_ROBOT.md)와 모션 탭 `▶ 실제 로봇 재생`(R2 시행 1개) → results/lab/. ③ 결과 그림: 주 채널 · R1 진폭비 · R3 단계 비교(정지 중 떨림 RMS 포함) · 한계 지도(computed + 실측 표시) · E vs N (docs/lab/MOTION_LAB.md, USABILITY.md)
setup_windows.bat / run_gui.bat                       # 팀원용 더블클릭(인수인계 2026-11-13): 온라인 설치(uv, constraints.txt) · GUI 실행. 팀원 사용법 docs/TEAM_GUIDE.md, 제출 체크리스트 docs/report/SUBMISSION_CHECKLIST.md
setup_mac.command / run_gui.command, setup_linux.sh / run_gui.sh   # macOS(Apple Silicon, 14+)·Linux(Ubuntu 22.04+) 같은 설치·실행 (2026-11-14, 실제 실행은 안 해 봄). 인수인계서 HANDOVER.md
.venv\Scripts\python tools\make_submission.py        # 교수님 제출용 소스 zip → dist/ (포함 목록은 스크립트 INCLUDE, --test = 푼 사본에서 테스트)
.venv\Scripts\python -m reachy_motion check success --variant both   # 초기 정책·비교 조건 (computed)
.venv\Scripts\python -m reachy_motion play success    # Mock 실시간 재생
.venv\Scripts\python -m reachy_motion sim-play success --variant expressive  # 로컬 MuJoCo viewer
.venv\Scripts\python -m reachy_motion sim-verify       # 8개 모션 MuJoCo 일괄 실행 + 검토 표 (simulated)
.venv\Scripts\python -m reachy_motion video            # motions/ + candidates/* 의 E|N 영상 (daemon 없는 오프라인 MuJoCo 재생, simulated, MP4 + index.html)
.venv\Scripts\python -m reachy_motion timing --duration 10  # 실행기 주기·지터 (pc_measured)
.venv\Scripts\python -m reachy_motion phase2           # 사양표·그림 재생성 (computed)
.venv\Scripts\python -m reachy_motion robot-status      # R0: 허용 GET 5개만 (기본 192.168.0.15; 모션·클라이언트·WebSocket 없음)
.venv\Scripts\python -m reachy_motion robot-r1 --r1 pitch:+2 --r0 <r0_report.json> --target mock   # R1 시행 1개: Mock 실행(안테나 유지 기동, 기동 램프·시행·복귀 램프를 각각 기록, results/lab). --target robot(CLI, 디버깅·비상용, 사용자가 직접): R0·진입 조건·승인 게이트 2개(--ramp-approval R1-0 램프, --approval 시행) → 운영자 환경 확인 → 연결·실행
.venv\Scripts\python -m reachy_motion approval-template --stage R1 --r1 pitch:+2 --r0 <r0_report.json> --part ramp  # 승인 양식 출력만 (파일 안 씀). --part ramp = R1-0 기동·복귀 램프(Stewart 최대 이동 89.9° 표시), --part trial = R1 시행. --c1이면 C1(토크 켜기·유지·끄기) 양식
.venv\Scripts\python -m reachy_motion robot-r1 --start awake --r1 pitch:+2 --r0 <r0_report.json>   # AWAKE: 평소 방식으로 깨운 로봇(토크 켜짐, INIT)에서 램프 없이 INIT → 시행 → INIT, 끝나면 깨어 있는 채 대기. robot-r2/r3도 --start awake. 승인은 시행 하나. docs/phase4/FIRST_ROBOT_TEST.md §1.11
.venv\Scripts\python -m reachy_motion robot-r2 --r0 <r0_report.json> --antennas hold   # R2: 확정 모션 E/N(기본 aha_recommend,boredom,success) Mock 실행. 실기기는 시행 하나씩 + C1·R1 기록(--c1-report, --r1-session) + 승인 2개(R1-0 램프, R2 세트). 안테나가 R0와 다르면 거부, hold = 머리만 진단
.venv\Scripts\python -m reachy_motion robot-r3 --duration 1.0 --r0 <r0_report.json> --antennas hold   # R3 한 단계(pitch 20° minjerk). 더 짧은 D는 --after <앞 단계 실행 폴더>(`robot_r1.R3_LIMITS` 안일 때만), 실기기 D < 0.2 s 거부 (2026-11-13: 사다리 1.0 → 0.2, 기준은 실측 기준선 대비). GUI 진폭 사다리는 D ≥ 1 s에서 A 10°부터 한 단계씩(`robot_r1.r3_amplitude_step_problems`). docs/phase4/FIRST_ROBOT_TEST.md §1.8
.venv\Scripts\python -m reachy_motion robot-c1 --r0 <r0_report.json>   # C1(CLI, 사용자가 직접): R0·진입 조건(네 범주)·승인 게이트 → 운영자 환경 확인(controlled) → run_c1 → c1_report.json. docs/phase4/FIRST_ROBOT_TEST.md
.venv\Scripts\python -m reachy_motion tracking results\phase3_sim\review\<시각>   # 추종 지표 (data_kind는 입력 그대로)
.venv\Scripts\python -m reachy_motion sim-startup --compare-wake-up   # 기동 절차 vs SDK wake_up (로컬 MuJoCo, simulated)
.venv\Scripts\python -m reachy_motion sim-stop          # S1/S2 정지 실험 6종 + 위치·속도 그래프 (로컬 MuJoCo, simulated)
```

`pytest`는 uv 캐시에 없어 쓰지 않는다(HW3와 같은 stdlib `unittest`).

## 코드 규칙

- 내부 단위는 SI(rad, m, s). deg/mm는 CLI·보고서 경계에서만, 변수명에 `_deg`/`_mm` 접미사.
- 머리 자세는 4×4 동차행렬, `reachy_mini.utils.create_head_pose`(Euler `"xyz"` roll/pitch/yaw, `utils/__init__.py:14-47`).
  **기본값이 `degrees=True`, `mm=False`(미터)** 이므로 내부 SI 값은 `create_head_pose(..., degrees=False)`로 넘긴다.
- 관절 벡터 순서: `[body_yaw, stewart_1..6]` + antennas `[right, left]` (`daemon/backend/robot/backend.py:206-209`).
- 결과물: `results/<phase>/` + `manifest.json`(버전, 명령, 파라미터, data_kind). 그림은 PNG.
- 문서는 한국어, 코드·주석은 영어. GUI 표시 문구는 한국어(`gui/ko.py`, 기술 용어·data_kind 값은 원어).
- git 저장소: https://github.com/j0126/reachy-hw4 (2026-11-14 사용자 요청으로 init·첫 push). 커밋·push는 사용자가 요청할 때만.
  올릴 파일은 `.gitignore`가 정한다(개발 기록·로그·다시 만들 수 있는 출력은 이 PC에만, HANDOVER.md §9). 팀원 인수인계서는 `HANDOVER.md`.

## 반드시 기억할 SDK 1.11.0 동작 (근거: `docs/phase1/SDK_ANALYSIS.md`)

- `goto_target()`은 클라이언트에서 보간하지 않는다: WS `TaskRequest` → daemon `Backend.goto_target` → `play_move`가
  `GotoMove`를 **100 Hz**로 평가(`daemon/backend/abstract.py:826-977`, `io/ws_server.py:174-200`).
  시작 자세는 **현재 측정 자세**(`get_present_head_pose`), 클라이언트는 `duration+1 s` 타임아웃으로 완료를 기다린다
  (`reachy_mini.py:672-722`).
- `goto_target(body_yaw=0.0)`이 **기본값** — body_yaw를 생략하면 몸통이 0 rad로 돌아간다(`reachy_mini.py:680`).
- `play_move` 루프는 `t < duration` 동안만 평가하고 끝에 목표를 다시 보내지 않는다(`abstract.py:904-925`) →
  LINEAR는 최종 명령이 g/D만큼 목표에 못 미친다(g = 마지막 간격, 공칭 10 ms → 10 ms/D; 실제 간격은 그 이상이라 최악은 더 큼).
  다른 3종은 끝 속도 0이라 무시할 수준.
- 실기기 제어 루프 **50 Hz**(`robot/backend.py:71`). 매 tick: 현재 관절 목표 write → 현재값 read → IK(다음 tick에 write)
  (`robot/backend.py:200-262`). `ik_required`는 IK가 끝나도 해제되지 않아 매 tick 재계산된다(`abstract.py:544-594, 609`).
- IK 실패(NaN)는 `ValueError` → 제어 루프가 0.5 s 간격 경고만 남기고 **이전 관절 목표 유지**(조용히 멈춤)
  (`abstract.py:586-588`, `robot/backend.py:253-261`).
- IK 엔진 기본값 `AnalyticalKinematics`(rust), `automatic_body_yaw=True`이면 `inverse_kinematics_safe`로
  **body yaw ≤ 160°, 머리-몸통 상대 yaw ≤ 65°** 제한(`kinematics/analytical_kinematics.py:80-95`).
  FK는 상태를 가진 Newton 반복이라 큰 점프 후에는 다른 해로 수렴할 수 있다 → 추종 분석은 관절공간 기준.
- 보간 4종 피크 속도 = k·A/D: linear 1, minjerk 1.875, ease_in_out 2, **cartoon 5.595**(±10.0% 예비동작·오버슈트).
- **daemon 측 goto 진입점 중 `method`가 반영되는 것은 Python `goto_target`뿐** — REST `/api/move/goto`, typed `goto_target` 명령은
  항상 MIN_JERK. 클라이언트 측 `play_move(GotoMove)`·자체 스트리밍은 어떤 방법이든 가능.
- move 실행 중에는 `set_target` 계열이 **조용히 무시**된다(`abstract.py:1661-1699`). goto와 스트리밍을 섞지 않는다.
- 토크 켜기: **전체** `enable_motors()`만 목표를 마지막 읽기 관절로 고정하고 목표 레지스터에 먼저 쓴 뒤 토크를 켠다
  (`robot/backend.py:352-377`). `ids`를 준 일부 켜기는 고정하지 않으므로 쓰지 않는다(`abstract.py:1786-1792`).
- **머리 목표가 없을 때 IK가 요구되면 목표 = 단위행렬(rest)**(`abstract.py:555-560`). 트래킹 끄기(`clear_tracking_aim`,
  `abstract.py:712-719`)와 흔들림 끄기→`set_speech_offsets`(`abstract.py:668-680`)가 IK를 요구한다 → 토크가 켜져 있으면 rest로
  계단 점프(MuJoCo 연결 직후 관찰). 실기기 연결은 **토크가 꺼진 상태에서** 그런 명령을 먼저 보내고 목표를 현재 자세로 맞춘 뒤
  전체 `enable_motors()`로 다시 고정한다. 다른 클라이언트가 켜 둔 트래킹 aim과 잠금 없는 IK 경합 때문이다
  (`reachy_motion/backends/robot_connect.py`, `docs/phase4/STARTUP_STOP.md` §8–8.2). 생성자 자체는 IK를 요구하지 않는다.
  트래킹 상태·일부 모터 켜짐·다른 클라이언트는 허용 GET으로 알 수 없다 → R0의 `r1_entry`는 항상 미충족이고 연결 순서가 거부한다.
- 끊긴 SDK 클라이언트는 `set_target` 등을 **오류 없이 버린다**(`io/ws_client.py:135-160`, MuJoCo에서 확인) → 측정 감시(S2)가
  유일한 감지 수단이고, 그때 마지막 새 측정 이후 보낸 명령은 미확인이다.
- SDK는 Stewart 관절 한계·속도·가속도·충돌을 **검사하지 않는다**. 공식 문서의 pitch/roll ±40° 클램프도 1.11.0엔 없다(#1449).
  관절 한계(URDF=MJCF): s1/s3 [−48,+80]°, s2 [−80,+70]°, s4/s6 [−80,+48]°, s5 [−70,+80]°, 몸통 ±160°.
- 명령값(target)은 어떤 공개 채널로도 나오지 않는다(`/api/state/full?with_target_*`는 필드가 버려짐 — sim에서 실증).
  측정 push에는 타임스탬프가 없다 → 명령은 클라이언트가 기록, 측정은 도착 시각(`perf_counter_ns`)으로.
- 모터(공식): Stewart XL330-M288-T ×6, 안테나 XL330-M077-T ×2, 몸통 XC330-M288-PG. Profile Velocity 미설정, P=300/200, D=0.
- 이 PC(Windows)의 sim daemon: asyncio 타이머가 15.6 ms 단위라 goto 평가가 100 Hz가 아님(유휴 ≈ 60 Hz, WS 브로드캐스트로 깨면
  ≈ 100–145 Hz 불규칙 — 스텁 결과, 실행 중 daemon은 미측정), MuJoCo 실시간 계수 ≈ 0.8–0.86, Stewart 응답은 마찰 지배적.
  느린 램프 1회 비교에서 sim은 실기기보다 훨씬 낙관적 → sim 지연·RMSE를 로봇 예측으로 쓰지 않는다.
- 실기기에서는 안테나가 머리보다 한 tick(≈ 20 ms) 앞선다(머리만 IK 후 다음 tick에 write). 명령 경로 지연 모델: 실기기 30–40 ms.
- 자동 body yaw의 머리 yaw ψ = atan2(−R01, R00)가 표본 사이 ±180°를 가로지르면 몸통 목표가 ≈ 229–275° 뒤집힌다(NaN 아님).
  원인: cartoon 외삽(0°에서 |목표 yaw| > 163.6°) 또는 기울어진 머리(반대 부호 roll·pitch 20°면 |yaw| ≥ 172.9°, 40°면 151.7°)
  → 안전검사는 연속 표본의 ψ 차 < 180°와 표본 간 관절 변화 상한으로 차단(|ψ| < 180°는 항상 참이라 검사가 아님).
