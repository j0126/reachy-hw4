# Reachy Mini 표현적 모션 — HRI Homework 4

Reachy Mini(Wireless)로 **의도·상태·반응을 전달하는 표현적 모션**을 설계하고, SDK가 로봇을 움직이는 방법과 물리적 한계를
실험·분석하는 프로젝트다(DGIST HRI). **Motion Lab GUI** 하나로 모션 재생, MuJoCo·실제 로봇 실험, 결과 분석, 보고서 자료 내보내기를 한다.

| 모션 | 전달하는 것 | 버전 |
|---|---|---|
| **A — aha_recommend** | 의도: "좋은 생각이 났어요, 이걸 추천해요" | Expressive / Neutral |
| **B — boredom** | 상태: 지루함·대기 | Expressive / Neutral |
| **C — success / failure** | 반응: 성공·실패 | Expressive / Neutral |

- **팀원은 [HANDOVER.md](HANDOVER.md)(인수인계서)부터** 읽는다: 현황·남은 일·모션 설계 의도·보고서·발표 자료·제출 목록·git.
- GUI 사용법과 실험 순서: [팀원 가이드](docs/TEAM_GUIDE.md) (GUI 오른쪽 위 `? 사용법`으로도 열린다).
- 저장소: https://github.com/j0126/reachy-hw4

## 1. 설치 (처음 한 번, 인터넷 필요)

| OS | 조건 | 설치 | GUI 실행 |
|---|---|---|---|
| Windows 10/11 (64-bit) | 실제로 확인함 | `setup_windows.bat` 더블클릭 | `run_gui.bat` 더블클릭 |
| macOS | Apple Silicon(M1 이후) + macOS 14 이상 | `setup_mac.command` 더블클릭 | `run_gui.command` 더블클릭 |
| Linux | Ubuntu 22.04 이상 (x86_64) | 터미널에서 `./setup_linux.sh` | `./run_gui.sh` 또는 앱 메뉴 `Reachy HW4 Motion Lab` |

1. **uv 설치** (Python 패키지 관리 도구, 한 번만). 설치 뒤 **새 터미널 창**을 연다. Python은 따로 설치하지 않아도 된다(uv가 3.12를 받는다).
   - Windows PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS·Linux 터미널: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Linux만**: reachy-mini가 쓰는 PyGObject를 이 PC에서 컴파일하므로 먼저
   `sudo apt install -y build-essential pkg-config libffi-dev libcairo2-dev libgirepository1.0-dev libxcb-cursor0 fonts-nanum pulseaudio-utils`
3. 위 표의 설치 스크립트를 실행한다. 마지막 줄에 `pins OK`가 나오면 끝이다(약 1–3분). 그다음부터는 GUI 실행 파일만 더블클릭한다.

직접 입력하려면 이 폴더에서:

```
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -c constraints.txt -e ".[sim,analysis,gui]" av    # Windows
uv pip install --python .venv/bin/python -c constraints.txt -e ".[sim,analysis,gui]" av            # macOS·Linux
.venv\Scripts\python -m reachy_motion env                                                         # macOS·Linux: .venv/bin/python
```

- `constraints.txt`가 모든 패키지 버전을 고정한다. **`reachy-mini`는 1.11.0이어야 한다**(로봇 daemon과 같은 버전). 업그레이드하지 않는다.
- Windows 11에서 검증했다. macOS·Linux 스크립트는 PyPI 휠 조건(onnxruntime 1.27.0은 macOS arm64·14 이상, PySide6 6.12.0은
  glibc 2.34 이상)에 맞춰 만들었고 실제로 실행해 보지 않았다. 문제가 생기면 [HANDOVER.md](HANDOVER.md) §2.4.
- macOS에서 더블클릭이 막히면(확인되지 않은 개발자): Finder에서 파일을 오른쪽 클릭 → 열기. 그래도 안 되면 터미널에서 `bash setup_mac.command`.

## 2. 실행

- GUI 실행 파일을 더블클릭하거나, 이 폴더에서 `.venv\Scripts\python -m reachy_motion gui` (macOS·Linux: `.venv/bin/python -m reachy_motion gui`)
- 반드시 이 폴더에서 실행한다. 결과가 이 폴더의 `results/lab`에 저장된다.
- 로봇이 없어도 된다. 기본 백엔드는 이 PC의 MuJoCo 시뮬레이션(127.0.0.1)이다.
- 화면: ① 모션 · ② 실험 · ③ 결과 (사용법: [팀원 가이드](docs/TEAM_GUIDE.md), 자세한 설명: [MOTION_LAB.md](docs/lab/MOTION_LAB.md))

## 3. 꼭 지킬 것 (실제 로봇)

- 실제 로봇은 GUI의 로봇 상자로만 조작한다. 같은 로봇을 대시보드 앱·다른 PC·CLI로 **동시에** 조작하지 않는다.
- 로봇 옆에 머리를 받칠 사람이 있고, 전원 스위치에 손이 닿아야 한다. 떨림·열·소리·모터 오류가 보이면 바로 `■ 정지` → 머리를 받치고 `토크 OFF`.
- 새 조건은 MuJoCo에서 먼저 해 본다. 작고 느리게 시작하고 한 번에 한 설정만 바꾼다.
- 자세한 실제 로봇 사용법: [GUI_ROBOT.md](docs/lab/GUI_ROBOT.md)

## 4. 문서 지도

| 문서 | 누가 · 언제 |
|---|---|
| [HANDOVER.md](HANDOVER.md) | **팀원 전원, 처음에**: 현황·남은 일·모션 설계 의도·보고서·발표 자료·제출 목록·git |
| [docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md) | GUI로 설치 → 실험 → 촬영 → 분석 → 보고서·발표 (GUI `? 사용법`) |
| [docs/report/SUBMISSION_CHECKLIST.md](docs/report/SUBMISSION_CHECKLIST.md) | 과제 요구사항별로 된 것·남은 것 |
| [docs/report/HW4_REPORT_DRAFT.md](docs/report/HW4_REPORT_DRAFT.md) | 보고서 초안 (빈칸을 채운다) |
| [docs/report/PRESENTATION_OUTLINE.md](docs/report/PRESENTATION_OUTLINE.md) | 발표 10분 구성안 |
| [docs/lab/GUI_ROBOT.md](docs/lab/GUI_ROBOT.md) | 실제 로봇 버튼·순서·이상할 때·알려진 제한(실측)·효과음 |
| [docs/lab/MOTION_LAB.md](docs/lab/MOTION_LAB.md) | GUI 전체 설명, 기록 파일 형식 |
| [docs/phase1/SDK_ANALYSIS.md](docs/phase1/SDK_ANALYSIS.md) | 과제 (1): SDK가 로봇을 움직이는 방법 (근거 목록: [SOURCE_REFERENCES.md](docs/phase1/SOURCE_REFERENCES.md)) |
| [docs/phase2/MOTION_DESIGN.md](docs/phase2/MOTION_DESIGN.md), [docs/phase3/MOTION_REPORT_TABLE.md](docs/phase3/MOTION_REPORT_TABLE.md) | 과제 (2): 설계 규칙, 보고서용 모션별 표 |
| [docs/phase3/MOTION_REVISIONS.md](docs/phase3/MOTION_REVISIONS.md), [BOREDOM_CANDIDATES.md](docs/phase3/BOREDOM_CANDIDATES.md), [MUJOCO_REVIEW.md](docs/phase3/MUJOCO_REVIEW.md) | 설계 과정: 수정 이력, boredom 후보 비교, MuJoCo 검토 |
| [docs/phase4/STARTUP_STOP.md](docs/phase4/STARTUP_STOP.md) | 연결·기동·정지가 왜 안전한지 (보고서 3.6) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 코드 구조 |
| [motions/sounds/README.md](motions/sounds/README.md) | 효과음 |
| [CLAUDE.md](CLAUDE.md) | AI 개발 도구용 규칙·SDK 동작 메모 (개발자용) |

## 5. 폴더 구조

```
reachy_hw4/
├── setup_windows.bat  run_gui.bat         Windows 설치 · GUI 실행 (더블클릭)
├── setup_mac.command  run_gui.command     macOS
├── setup_linux.sh     run_gui.sh          Linux
├── README.md  HANDOVER.md  CLAUDE.md  pyproject.toml  constraints.txt
├── motions/          확정 모션 8개 (<name>.<variant>.yaml), sounds/ 효과음, candidates/ 이전 버전·후보
├── reachy_motion/    코드 (gui = Motion Lab, library·planner·safety·executor·backends·analysis)
├── tests/            자동 테스트 (네트워크·로봇 없이)
├── tools/            make_submission.py (교수님 제출용 소스 zip)
├── docs/             설명서·보고서 초안·분석
└── results/
    ├── phase1/        과제 (1) 그림·표 (computed)
    ├── phase2/        모션 사양 그림·비교 (computed)
    ├── phase3_sim/    MuJoCo 검토·E|N 나란히 영상 (simulated). 확정 모션 영상: videos/20261114_013401
    ├── phase4/        기동·정지 시뮬레이션, 추종 분석
    └── lab/           GUI 실험 기록 <시각>_<sim|robot>_<R1|R2|R3>/runs/<시행>/ (실제 로봇 = measured)
```

## 6. 개발자용

```
.venv\Scripts\python -m unittest discover -s tests -t .      # 전체 테스트 (네트워크·로봇 없음)
.venv\Scripts\python -m reachy_motion env                     # 버전·핀 확인
.venv\Scripts\python -m reachy_motion phase1                  # 과제 (1) 그림·표 다시 만들기 (computed)
.venv\Scripts\python -m reachy_motion video --dir motions     # MuJoCo E|N 영상 다시 만들기 (simulated)
.venv\Scripts\python tools\make_submission.py                 # 교수님 제출용 소스 zip → dist/
```

macOS·Linux에서는 `.venv\Scripts\python` 대신 `.venv/bin/python`을 쓴다.
CLI의 실제 로봇 명령(`robot-c1/r1/r2/r3`, 승인 파일)은 디버깅·비상용이다. 팀원은 쓰지 않는다. 명령 전체 목록은 [CLAUDE.md](CLAUDE.md).
