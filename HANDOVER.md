# 인수인계서 — Reachy Mini HW4 표현적 모션 (2026-11-14)

개발 담당이 없어도 팀원이 실험·분석·촬영·보고서·발표·제출을 끝낼 수 있게 정리한 문서다.

- 저장소: https://github.com/j0126/reachy-hw4
- 마감: **제출 11/16(월) 23:59**, **발표 11/17(화)** (HW4 10분 + Term Project 제안 5분)
- 함께 볼 문서: GUI 사용법·실험 순서는 [docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md), 과제 요구사항별 상태는
  [docs/report/SUBMISSION_CHECKLIST.md](docs/report/SUBMISSION_CHECKLIST.md)

**숫자 읽는 법 (data_kind)**: 모든 숫자와 그림에는 출처를 붙인다. 보고서에도 그대로 쓴다.

| 표시 | 뜻 |
|---|---|
| `measured` [M] | 실제 로봇에서 측정 |
| `simulated` [Sim] | MuJoCo 시뮬레이션 |
| `computed` [C] | SDK 보간·IK로 계산한 계획값 |
| `pc_measured` | 이 PC에서 잰 값(실행기 주기, 요청 시간). 로봇 측정이 아님 |
| `mock` | 테스트용 합성 모델. 결과로 쓰지 않음 |

V/A(valence·arousal) 값은 **설계 목표**다. 측정한 값이 아니다.

---

## 0. 한눈에

| | 상태 |
|---|---|
| 과제 (1) SDK가 로봇을 움직이는 방법 | 끝. 보고서 초안 1절과 그림 fig1–fig5 |
| 과제 (2) 표현 모션 4종 × Expressive/Neutral = 8개 | 끝. 11/11 확정, 11/14 효과음 추가(수정 2차), failure Neutral 도리질 폭 맞춤(수정 3차) |
| 과제 (3) 물리 한계: 정의·추정 | 끝 (computed) |
| 과제 (3) 물리 한계: 실제 로봇 시험 | 일부. R1 끝, R2는 Expressive 4개와 success Neutral, R3는 D 1.0 → 0.4까지 |
| 도구 | Motion Lab GUI: ① 모션 · ② 실험 · ③ 결과. MuJoCo와 실제 로봇 실행, 측정 기록, 그림·표 내보내기 |
| 남은 일 | Neutral 실측 3개, R3 D 0.3 → 0.2, 촬영, 보고서 빈칸, 슬라이드, 리허설, 제출 zip (§1) |

## 1. 남은 일 (이 순서로)

| # | 할 일 | 누가 (예시) | 어디를 보나 | 끝났다는 표시 |
|---|---|---|---|---|
| 1 | 각자 노트북에 설치하고 GUI 띄우기 | 전원 | §2 | 설치 마지막 줄 `pins OK`, 창이 뜸 |
| 2 | MuJoCo로 리허설: R2 짝 몇 개, R3 사다리 끝까지 | 조작 | TEAM_GUIDE §4.6 | `results/lab/<시각>_sim_*` 생김 |
| 3 | 실제 로봇 R2 **Neutral 3개**: aha N, boredom N, failure N. 같은 날 Expressive도 한 번씩 다시(같은 조건 비교) | 조작·안전·촬영 | TEAM_GUIDE §4.3 | 결과 탭에 E/N 짝이 모두 있음 |
| 4 | 실제 로봇 R3 **D 사다리**: 한 연결 안에서 D 1.0 → 0.6 → 0.4 → 0.3 → 0.25 → 0.2 s, 한 단계씩 | 조작·안전·촬영 | TEAM_GUIDE §4.4, 이 문서 §5 | 무너진 단계 또는 0.2까지 기준 안 |
| 5 | (선택) 진폭 사다리: D 1.0에서 A 10 → 20 → 30° | 조작 | TEAM_GUIDE §4.4 6번 | |
| 6 | 결과 탭 → `보고서 자료 내보내기` → 표 3.4a·3.5a, 그림 | 분석 | 이 문서 §6 | 표 빈칸 없음 |
| 7 | 영상 편집 (2–3분, 자막: 모션·E/N·D) | 촬영 | TEAM_GUIDE §5 | |
| 8 | 보고서: 팀 표(이름·학번·기여), 3.4·3.5, 요약·결론, 한계 | 보고서 | [HW4_REPORT_DRAFT.md](docs/report/HW4_REPORT_DRAFT.md), 이 문서 §7 | |
| 9 | 슬라이드 | 발표 | [PRESENTATION_OUTLINE.md](docs/report/PRESENTATION_OUTLINE.md), 이 문서 §6.2 | |
| 10 | 리허설: 같은 노트북·같은 Wi-Fi로 처음부터 끝까지 한 번 | 발표·조작 | TEAM_GUIDE §8 | |
| 11 | 제출: 보고서 + 소스 zip + 영상 | 제출 | 이 문서 §8 | |

실제 로봇을 쓰는 날(3·4번)은 약 1시간 30분을 잡는다. 3과 4를 하면서 바로 촬영한다(7번 재료).

---

## 2. 시작하기 (Windows · macOS · Linux)

### 2.1 받기

```
git clone https://github.com/j0126/reachy-hw4.git
```

git을 모르면 GitHub 페이지 `Code → Download ZIP`으로 받아 압축을 풀어도 된다. macOS는 ZIP보다 `git clone`을 권한다(ZIP으로 받은
스크립트는 더블클릭이 막힐 수 있다, §2.4). 저장소가 비공개라면 주인이 GitHub `Settings → Collaborators`에서 초대해야 받을 수 있다.

### 2.2 설치와 실행

| OS | 조건 | 설치 (처음 한 번) | GUI 실행 |
|---|---|---|---|
| Windows 10/11 | 64-bit. **실제로 확인함** | `setup_windows.bat` 더블클릭 | `run_gui.bat` 더블클릭 |
| macOS | Apple Silicon(M1 이후) + macOS 14 이상. 확인 안 함 | `setup_mac.command` 더블클릭 | `run_gui.command` 더블클릭 |
| Linux | Ubuntu 22.04 이상(x86_64). 확인 안 함 | apt 패키지(§2.4) → 터미널에서 `./setup_linux.sh` | `./run_gui.sh` 또는 앱 메뉴 `Reachy HW4 Motion Lab` |

1. **uv 설치** (한 번만, 설치 뒤 새 터미널 창)
   - Windows PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS·Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. 설치 스크립트 실행 → 마지막 줄 **`pins OK`**. 인터넷이 필요하고 1–3분 걸린다. Python은 uv가 3.12를 받는다.
3. GUI 실행 → Motion Lab 창. 결과는 항상 이 폴더의 `results/lab`에 쌓인다.

### 2.3 설치 스크립트가 하는 일

- `.venv` 폴더를 만들고 `constraints.txt`의 버전 그대로 설치한다. `reachy-mini==1.11.0`(로봇 daemon과 같은 버전)이다.
  **업그레이드하지 않는다.** 다른 버전이면 `pins OK`가 나오지 않는다.
- 끝에 `python -m reachy_motion env`로 버전을 확인한다.
- Linux 스크립트는 끝에 앱 메뉴 바로가기(`~/.local/share/applications/reachy-hw4-motion-lab.desktop`)를 만들지 묻는다.

### 2.4 OS별 주의

**macOS**
- Intel Mac은 안 된다. reachy-mini 1.11.0이 쓰는 onnxruntime 1.27.0에 Intel Mac용 설치 파일이 없다(PyPI 확인, 2026-11-14).
  이때는 Windows 노트북을 쓴다.
- 더블클릭이 "확인되지 않은 개발자"로 막히면 Finder에서 오른쪽 클릭 → 열기. ZIP으로 받았다면 터미널에서
  `xattr -dr com.apple.quarantine <폴더>`를 실행하거나 `bash setup_mac.command`로 실행한다.
- `Permission denied`가 나오면 그 폴더에서 `chmod +x *.command *.sh`.
- MuJoCo viewer 창은 macOS에서 `mjpython`으로만 뜬다. 코드가 알아서 처리하고, `mjpython`이 없으면 창 없이 계산만 한다.

**Linux (Ubuntu·Debian)**
- reachy-mini가 Linux에서 쓰는 PyGObject는 설치할 때 컴파일되므로 먼저 아래를 설치한다. 없으면 `setup_linux.sh`가 이 줄을 보여 주고 멈춘다.
  ```
  sudo apt install -y build-essential pkg-config libffi-dev libcairo2-dev libgirepository1.0-dev libxcb-cursor0 fonts-nanum pulseaudio-utils
  ```
- `fonts-nanum`이 없으면 한글이 네모로 나온다. `libxcb-cursor0`이 없으면 Qt 창이 뜨지 않는다(`xcb` 오류).
- Ubuntu 20.04는 안 된다(PySide6 6.12.0에 glibc 2.34 이상 필요).

**모든 OS**
- 실제 로봇과 노트북은 같은 Wi-Fi에 있어야 한다. 로봇 IP는 지금까지 `192.168.0.15`였다. 다른 네트워크에서는 바뀔 수 있으니 로봇 상자 IP 칸에 입력한다.
- 실행은 반드시 저장소 폴더 안에서 한다(실행 파일이 알아서 그 폴더로 이동한다).
- GUI가 이상하게 꺼지면 함께 열린 검은 창(터미널)의 마지막 오류를 캡처한다.

### 2.5 설치가 맞는지 확인 (선택)

```
.venv\Scripts\python -m unittest discover -s tests -t .          (Windows)
.venv/bin/python -m unittest discover -s tests -t .              (macOS·Linux)
```

네트워크·로봇 없이 도는 자동 테스트다(약 730개, 몇 분). 마지막 줄이 `OK`면 된다.

---

## 3. 모션은 어떻게 만들었나 (보고서 2절, 발표 5–7장 재료)

### 3.1 시나리오

Term Project인 **Reachy Café**의 바리스타 로봇이 손님과 소통하는 순간 세 가지를 골랐다.

| 과제 범주 | 모션 | 카페 상황 | 전달하려는 것 |
|---|---|---|---|
| (A) 의도 | `aha_recommend` | 추천 메뉴를 정하고 손님에게 보여 주기 직전 | "좋은 생각이 났어요, 이걸 추천해요" |
| (B) 상태·감정 | `boredom` | 손님이 없어 기다림 | "지루하다, 아무도 안 온다" |
| (C) 반응 | `success` / `failure` | 주문 처리 성공·실패 | "됐다!" / "아, 안 됐다…" |

트리거는 지금은 버튼(GUI `▶ 실제 로봇 재생`)이다. Term Project에서는 상위 FSM이 이벤트에 맞춰 `MotionService.play(name, variant)`를 부른다.

### 3.2 만든 과정

| 날짜 | 단계 | 한 일 | 자세한 문서 |
|---|---|---|---|
| 11/10 | SDK 분석 | SDK 1.11.0 소스를 읽고 `goto_target` 경로, 보간 4종, IK, 50 Hz 루프, 한계 처리를 정리 | [SDK_ANALYSIS.md](docs/phase1/SDK_ANALYSIS.md) |
| 11/10 | 초안 8개 | 강의 논문 [06]·[09]의 동작 단서(위로 = 긍정, 아래로 = 부정, forethought·reaction)와 애니메이션 원리를 키프레임으로 옮긴 출발점. 계산 검사(관절 여유, 모터 속도 비)로 범위 확인 | [MOTION_DESIGN.md](docs/phase2/MOTION_DESIGN.md), [MOTION_SPECS.md](docs/phase2/MOTION_SPECS.md) |
| 11/10–11 | MuJoCo 검토 | 8개를 MuJoCo에서 실행하고 E\|N 나란히 영상으로 봄. boredom 후보 3개(scan·story·doze)를 더 만들어 비교 | [MUJOCO_REVIEW.md](docs/phase3/MUJOCO_REVIEW.md), [BOREDOM_CANDIDATES.md](docs/phase3/BOREDOM_CANDIDATES.md) |
| 11/11 | 수정 1차 → 확정 | 영상 검토 의견: aha는 깨달음 순간을 더 강조, boredom은 story 후보를 7–8 s로, success·failure는 그대로. 수정 뒤 8개 확정(`draft: false`) | [MOTION_REVISIONS.md](docs/phase3/MOTION_REVISIONS.md) |
| 11/12–14 | 실제 로봇 | R1·R2·R3 실행, 머리 추종 특성(작은 명령은 안 움직임, 약 0.19 s 지연) 발견 | [GUI_ROBOT.md](docs/lab/GUI_ROBOT.md) '알려진 제한' |
| 11/14 | 수정 2차 | failure·boredom Expressive에도 효과음(움직임은 그대로). 로봇 스피커에서 네 소리 모두 재생 확인 | [MOTION_REVISIONS.md](docs/phase3/MOTION_REVISIONS.md) 끝, [motions/sounds/README.md](motions/sounds/README.md) |
| 11/14 | 수정 3차 | 최종 검토에서 failure Neutral 도리질(±12°)이 Expressive(±10°)보다 큰 것을 찾아 ±10°로 맞춤(20 °/s, 길이 그대로). failure N은 실측 전이라 기존 기록에 영향 없음 | [MOTION_REVISIONS.md](docs/phase3/MOTION_REVISIONS.md) 끝 |

초안은 개발 과정에서 도구(Claude Code)가 논문 단서를 키프레임으로 옮겨 만든 출발점이다. 무엇을 바꾸고 무엇을 확정할지는 학생이
MuJoCo 영상을 보고 정했다(위 표의 검토 의견). 과제에 AI 도구 사용 표기 규정이 있으면 보고서에 그대로 적는다.

### 3.3 공통 설계 규칙

- **부호**: +pitch = 고개 숙임, +yaw = 로봇 왼쪽. roll 부호는 실제 로봇에서 따로 확인하지 않았다(영상으로 확인할 것, §7.2).
- **안테나**: `[오른쪽, 왼쪽]` 각도. rest는 −10° / +10°. 처짐 = 오른쪽은 더 −, 왼쪽은 더 +. 세움 = 0° 쪽.
  방향은 SDK의 잠자는 자세에서 추론했다(영상으로 확인할 것).
- **시작·끝**: 8개 모두 rest 자세(머리 0, 안테나 rest, 몸통 0)에서 시작해 rest로 끝난다.
- **V/A 단서**: 위로 들기·안테나 세움 = 긍정 valence, 숙임·처짐 = 부정 valence. 속도·진폭·템포 = arousal.
- **애니메이션 원리**(강의 용어): anticipation, timing, exaggeration, slow in·slow out, follow-through, secondary action, staging.
  논문 [06]의 forethought(행동 직전에 생각을 보여 줌)·reaction(결과에 반응)도 쓴다.
- **계산 안전 범위**: 관절 여유 ≥ 10°(목표 15°), 가장 바쁜 Stewart 모터의 요구 속도 ÷ 무부하 속도 ≤ 0.5(목표 0.40).
  초기 정책일 뿐 기구적 안전을 보장하지 않는다.

### 3.4 모션별 의도와 설계

| 모션 | 의도한 읽힘 (E) | V / A 목표 (E · N) | 움직임 (E) | 왜 이렇게 | 효과음 (E) | 길이 E / N | 속도 비 E / N [C] |
|---|---|---|---|---|---|---|---|
| **A aha_recommend** | "생각하다가 좋은 생각이 났다 → 이걸 추천한다" | +0.7 / +0.6 · +0.2 / +0.1 | think: 고개 숙이고 안테나 처짐, 0.3 s 정지 → pop: cartoon으로 빠르게 위로 + 안테나 세움, 0.35 s 정지 → present: 왼쪽 22° 응시와 머리 기울임, 0.6 s 정지 → 복귀 | forethought(행동 전에 생각을 보여 줌). 정지로 '생각'과 '깨달음'을 나눔(수정 1차). 위로 = 긍정·자신감 | `aha.wav` 0.85 s: 빠르게 올라가는 종소리 두 번 | 3.50 / 2.60 s | 0.386 / 0.020 |
| **B boredom** | "누가 오나 둘러봤지만 아무도 없어 축 처진다" | −0.5 / −0.6 · 0.0 / −0.3 | 살짝 숙임 → 천천히 왼쪽(1.2 s) → 천천히 오른쪽(1.8 s), 양 끝 0.5 s 정지 → 축 처짐(pitch 20°, z −12 mm, 0.9 s 정지) → 복귀. 안테나 점점 처짐 | 둘러봄 → 아무도 없음 → 처짐의 이야기(story 후보). 빠른 스캔은 호기심으로 읽혀서 느리게(최고 39·52 °/s). 마지막 처짐이 가장 깊음 | `boredom.wav` 4.9 s: 한숨 같은 낮은 소리, 아주 작게 | 7.90 / 7.70 s | 0.087 / 0.017 |
| **C success** | "됐다! 신난다" | +0.8 / +0.6 · +0.3 / 0.0 | 웅크림 → cartoon으로 튀어 오름(z +5 mm) → 빠른 끄덕임 두 번 → 복귀. 안테나 세우고 세 번 흔듦 | reaction. 경쾌한 속도와 위로 튀는 동작 = 긍정·고각성([06]) | `success.wav` 0.3 s: 밝게 올라가는 장조 아르페지오 | 2.10 / 2.00 s | 0.372 / 0.023 |
| **C failure** | "아, 안 됐다… (실망)" | −0.6 / −0.3 · −0.2 / 0.0 | 짧게 움찔 → 고개와 안테나가 함께 처짐(roll −8°, pitch 18°, 안테나 70°) → 숙인 채 도리질 두 번 → 천천히 회복 | reaction. 느리게 처지는 실패 반응([06]), 아래로 = 부정 | `failure.wav` 0.2 s: 내려가는 단조 두 음 "어-어", 조금 작게 | 3.70 / 2.00 s | 0.096 / 0.011 |

- 전체 값(키프레임별 이동 시간·정지·보간·최고 속도, 관절 여유)과 참고 논문 요약: [MOTION_REPORT_TABLE.md](docs/phase3/MOTION_REPORT_TABLE.md).
  보고서 2.2에는 이 표를 옮긴다. GUI ① 모션 탭 `설정값`에도 같은 표가 나온다.
- 원본은 `motions/<모션>.<expressive|neutral>.yaml`이다. 설정값이 코드(YAML)에 그대로 있다는 것이 과제 요구다.

### 3.5 Neutral: 과제 조건과 우리가 지킨 방법

- 과제 조건: 같은 시작·끝 자세, 일정한 속도, 안테나 움직임·소리 없음.
- 우리 정의: [06]의 비교 조건처럼 **과제에 필요한 기능 동작만** 일정한 속도(linear, 키마다 같은 각속도)로 한다.
  - aha N = 왼쪽 22°를 본다, boredom N = 좌우를 본다, success N = 두 번 끄덕인다, failure N = 도리질한다.
  - failure N의 도리질 폭은 수정 3차(11/14)에서 E와 같은 ±10°로 맞췄다(전에는 ±12°).
- 확인(2026-11-14, computed): 4쌍 모두 시작·끝 차이 0, 한 가지 속도, 안테나 키 0개, 소리 없음, 비교 검사 문제 0건.
  `python -m reachy_motion check <모션> --variant both`로 다시 확인할 수 있다.

### 3.6 효과음

- Expressive 4개만 소리가 있다. Neutral은 과제대로 소리가 없다. 그래서 네 모션 모두 E와 N이 움직임·안테나·소리에서 다르다.
- 규칙(V/A 목표에서): valence → 음의 방향과 조(긍정 = 올라감·장조, 부정 = 내려감·단조), arousal → 빠르기·높이·크기.
- 소리는 직접 합성했다(`reachy_motion/sound.py`). 다른 사람의 음원을 쓰지 않았다.
- GUI 기본은 **로봇 스피커**다. 안 나면 모션 탭 `효과음`에서 `노트북 스피커`로 바꾼다. 소리가 모션보다 먼저 들리면 `시각 보정`을 +로.
- 한계: 효과음처럼 들린다(earcon). 사람이 잘 읽는지 평가하지 않았다.

### 3.7 모션을 바꾸고 싶다면

- 확정 파일(`motions/*.yaml`)은 팀이 합의했을 때만 고친다. 고치면 [MOTION_REVISIONS.md](docs/phase3/MOTION_REVISIONS.md)에 새 수정 차수로 적는다.
- 순서: YAML 수정 → `check <모션> --variant both` → `phase2`(사양표 다시 만들기) → MuJoCo 재생 → 실제 로봇.
- 마감 직전에는 바꾸지 않는 것이 안전하다. 이미 잰 실측 기록과 다른 모션이 되기 때문이다.

---

## 4. SDK 요약 (과제 1, 보고서 1절, 발표 2–4장)

- `goto_target()`은 클라이언트가 보간하지 않는다. daemon이 **현재 측정 자세**에서 목표까지 `duration` 동안 100 Hz로 보간한다.
  호출자는 `duration + 1 s`까지 기다린다. `body_yaw`를 생략하면 몸통이 0°로 돌아간다(기본값 0.0).
- 보간 4종의 피크 속도 = k·A/D: linear 1, minjerk 1.875, ease_in_out 2, **cartoon 5.595**. cartoon은 시작 전 −10 %, 목표 뒤 +10 %로
  명령 자체가 구간 밖으로 나간다.
- 제어 루프는 50 Hz다. tick마다 "이전 IK 결과 쓰기 → 읽기 → IK"라 머리 명령은 한 tick(20 ms) 늦고 안테나가 먼저 간다.
- IK: 머리 6자유도 → Stewart 모터 6개 + 몸통 yaw. 해가 없으면(NaN) daemon은 경고만 남기고 **직전 목표를 유지한다**(조용히 멈춤).
- SDK는 Stewart 관절 한계·속도·가속·충돌을 **검사하지 않는다**. 공식 문서의 roll·pitch ±40°도 1.11.0에서는 적용되지 않는다.
- 그림: `results/phase1/figures/` (fig1 보간 정규화, fig2 물리 단위, fig3 관절 공간, fig4 끝점 미달, fig5 명령 경로). 근거: 보고서 초안 1절,
  [SDK_ANALYSIS.md](docs/phase1/SDK_ANALYSIS.md), [SOURCE_REFERENCES.md](docs/phase1/SOURCE_REFERENCES.md)(주장마다 소스 파일:줄).

---

## 5. 물리 한계 (과제 3, 보고서 3절, 발표 8–9장)

### 5.1 정의와 추정 [C]

- **불가능한 모션**: 관절 한계 밖 자세(Stewart 관절, 몸통 ±160°, 머리–몸통 상대 yaw 65°), 또는 모터가 낼 수 없는 속도·가속을 요구하는 모션.
- **속도 추정**: IK로 관절 궤적을 구해 가장 바쁜 Stewart 모터의 피크 속도 ÷ XL330-M288-T 무부하 속도(618 °/s, 5 V). 보고서 표 3.2.
- **가속**: e-manual에 한계 값이 없다. 실제 로봇에서 이미 문제없이 실행한 aha E의 관절 가속(2941 °/s² [C])을 경험적 상한으로 쓴다.

| R3 pitch 20° minjerk | D 1.0 | 0.6 | 0.4 | 0.3 | 0.25 | 0.2 s |
|---|---|---|---|---|---|---|
| 속도 비 [C] | 0.044 | 0.073 | 0.110 | 0.146 | 0.175 | 0.219 |
| 관절 최대 가속 [C] (°/s²) | 87 | 243 | 545 | 967 | 1391 | 2166 |

확정 모션의 속도 비 [C]: aha E 0.386, success E 0.372, failure E 0.096, boredom E 0.087, Neutral 0.011–0.023.

### 5.2 시험 방법 (GUI ② 실험 탭)

| 실험 | 무엇 | 실행 |
|---|---|---|
| R1 동작 확인 | 축 하나를 작게(회전 0.1–15°, z 0.1–8 mm, 안테나 0.1–45°) 움직였다 돌아옴. 작은 명령이 실행되는지 | 축·진폭·방향 고르고 `▶ 실행` |
| R2 표현 모션 | 확정 모션 E/N을 그대로 실행하고 명령 vs 측정 기록 | 모션 탭 `▶ 실제 로봇 재생` 또는 실험 탭 R2 |
| R3 한계 시험 | pitch 20° minjerk에서 D를 한 단계씩 줄임. 추종이 무너지는 지점 찾기 | 한 단계씩 `▶ 실행`. 앞 단계가 기준을 넘으면 GUI가 다음 단계를 거부 |

**R3 무너짐 기준**(앞 단계가 하나라도 넘으면 다음 단계 거부): 진폭비 < 0.8, 지연 보정 RMSE > 진폭의 15 %, 오버슈트 > 진폭의 15 %,
지연(r² ≥ 0.9)이 같은 사다리 D 1.0보다 100 ms 넘게 늘어남, 완료 못 함·정지(S2·S3)·오류. 사람이 본 떨림·소리·열도 포함한다.
일정한 지연(약 0.19 s)만으로는 멈추지 않는다. 실제 로봇에서 D < 0.2 s는 하지 않는다(GUI가 막는다). 연결을 끊었다 다시 하면 D 1.0부터.

과제의 무너짐 종류와 우리가 보는 수치: lag = 지연, overshoot = 오버슈트, clipping = 진폭비, shaking = 정지 중 떨림 RMS(표시만),
motor error = 완료 못 함·정지·오류(모터 오류 레지스터는 허용된 읽기로 볼 수 없어 사람이 LED·소리·열로 확인).

### 5.3 지금까지 실측 [M] (기록은 `results/lab/`, 목록은 TEAM_GUIDE §4.0)

| 무엇 | 결과 |
|---|---|
| 작은 명령 (R1 yaw·pitch 2°) | 거의 안 움직임. 진폭비 0.12–0.20. IK가 요구하는 관절 변화 0.6°에 관절이 0° 움직임(데드밴드) |
| R1 yaw 10°, z 5 mm | 진폭비 0.53–0.69, 0.62–0.72. 목표 2–7° 앞에서 멈추고 돌아올 때도 다 오지 못함(정상 상태 오차) |
| 안테나 30° | 진폭비 1.01, 지연 68 ms. 명령 경로(PC → SDK → daemon)는 정상이고 차이는 머리 기구·모터 제어에서 생김 |
| 머리 지연 | 약 0.19 s (184–193 ms, r² ≥ 0.95) |
| R3 D 1.0 → 0.6 → 0.4 (11/13, 한 연결) | 모두 기준 안. 진폭비 1.03 · 0.89 · 0.93, 지연 192 · 164 · 159 ms, 지연 보정 RMSE 진폭의 6.6 · 6.4 · 5.7 %, 오버슈트 ≤ 0.6 %, 떨림 RMS 0.012–0.014°. **다음은 D 0.3부터** |
| R2 Expressive (11/12–14) | 주 채널 진폭비: aha 0.97–1.07(yaw, 6회), boredom 0.87–0.89(yaw, 3회), success 0.91(pitch, 3회), failure 1.14(pitch, 2회). success N 0.98(1회). failure E의 숙인 채 도리질(yaw)은 0.67–0.68 |
| 효과음 | 로봇 스피커에서 4개 모두 재생(사람이 들어서 확인). 재생 요청 71–90 ms [pc_measured] |

**해석** [S]: 머리 모터는 P 제어만 쓴다(P=300, I=0, D=0, SDK 설정 파일). 오차에 비례한 힘만 내므로 무게·마찰을 이길 만큼 오차가
커져야 움직이고(데드밴드·지연), 그만큼의 오차를 남긴다. SDK에 고정된 값이라 바꿔 보지 않았다.

### 5.4 "추정을 시험하라"에 답하는 문단 (보고서 3.4 결론에 넣을 것)

- 추정(5.1)은 D를 줄이면 **모터 속도·가속**이 먼저 한계에 닿는다고 본다. R3 D 0.2도 속도 비 0.22라 무부하 속도보다 한참 아래다.
- 실측은 그보다 먼저 **P 제어 특성**이 보인다: 작은 명령이 무시되고(데드밴드), 목표 앞에서 멈추고(정상 상태 오차), 항상 약 0.19 s 늦다.
- 그래서 "속도 비 < 1이면 된다"는 필요조건일 뿐이고, 실제 추종 품질은 제어 방식이 정한다는 것이 우리 결론의 뼈대다.
  D 0.3 → 0.2 결과(남은 일 4)로 이 문단을 마무리한다: 무너졌다면 어느 기준이 먼저 넘었는지, 무너지지 않았다면 "0.2 s까지는 기준 안"이라고 적는다.

---

## 6. 보고서·발표 자료 지도

### 6.1 보고서 (초안: [HW4_REPORT_DRAFT.md](docs/report/HW4_REPORT_DRAFT.md))

| 보고서 절 | 내용 | 가져올 곳 | data_kind |
|---|---|---|---|
| 팀 | 이름·학번·개인 기여 | 직접 작성 | — |
| 1.1–1.5 | SDK 경로, 보간 4종, IK, 주기, 한계 | 초안 1절 그대로 + `results/phase1/figures/fig1`–`fig5` | [S][C] |
| 2.1–2.3 | 시나리오, 모션별 표, Neutral | [MOTION_REPORT_TABLE.md](docs/phase3/MOTION_REPORT_TABLE.md)에서 옮김. 이 문서 §3 | 설계 목표·[C] |
| 2.4 | MuJoCo 확인 | `results/phase3_sim/review/20261111_171914/`, 영상 `results/phase3_sim/videos/20261114_013401/` | [Sim] |
| 3.1–3.2 | 한계 정의·추정 | 초안 그대로 (표 3.2) | [C] |
| 3.4 표 3.4a | R3 단계별 추종 | 내보내기 `r3_ladder.csv`, 그림 `r3_ladder.png`, `main_channel.png`, `joints.png` | [M] |
| 3.4.1 | 작은 명령·지연 | 초안에 이미 있음 + 그림 `r1_amplitude.png` | [M] |
| 3.4 그림 3.4d / 3.5 | 모션이 한계 안인가 | `limit_map.png`(계산 속도·가속 위에 실제 로봇 실행 = 원, 무너진 단계 = X) | [C] + [M] |
| 3.5 표 3.5a | R2 E/N 추종 | `expressive_vs_neutral.csv`, `expressive_vs_neutral.png`, `key_metrics.csv` | [M] |
| 3.6 | 안전 절차 | 초안 그대로, 근거 [STARTUP_STOP.md](docs/phase4/STARTUP_STOP.md) | [S] |
| 요약·결론·한계 | | 이 문서 §5.4, §7.3 | |

**그림·표 만드는 법**: ③ 결과 탭 → 세션 `불러오기` → 왼쪽에서 볼 시행 체크(같은 data_kind끼리) → `보고서 자료 내보내기` →
`results/lab/exports/<시각>_report/`. 이 폴더는 git에 올리지 않는다(언제든 다시 만들 수 있다). 보고서에 넣을 그림만 따로 모은다.

### 6.2 발표 10분 (구성안: [PRESENTATION_OUTLINE.md](docs/report/PRESENTATION_OUTLINE.md))

| 시간 | 내용 | 자료 |
|---|---|---|
| 0:00–0:40 | 팀, Reachy Café, 범주 A·B·C | §3.1 |
| 0:40–3:30 | SDK 경로, 보간 4종, IK·주기·한계 | fig5, fig1, fig2, fig3 |
| 3:30–6:00 | 모션 설계 + **라이브 시연**(Neutral → Expressive) | §3.4 표, 로봇 |
| 6:00–8:30 | 물리 한계: 정의 → 추정 → 실측(데드밴드·지연, R3 무너진 지점), 우리 모션이 그 안인지 | 표 3.2, `r1_amplitude.png`, `r3_ladder.png`, `limit_map.png`, 영상 |
| 8:30–10:00 | 안전 절차, 정리 | §10 |

라이브 시연: GUI 실행 → 창 위쪽 로봇 상자에서 연결 → (필요하면) Wake-up → ① 모션 탭에서 모션·변형 고르기 → `▶ 실제 로봇 재생`.
연결이 한 번 실패하면 바로 백업 영상(실제 로봇 촬영본, MuJoCo `results/phase3_sim/videos/20261114_013401/`)으로 넘어간다.

---

## 7. 최종 검토 결과: 알고 있어야 할 것

### 7.1 아직 안 된 것

- 실제 로봇 Neutral 실측 3개(aha·boredom·failure). 없으면 E/N 비교 표 3.5a가 비고, 시연 영상도 짝이 안 맞는다.
- R3 D 0.3 → 0.25 → 0.2. 무너지는 지점이 과제 (3)의 핵심 결과다.
- 촬영(효과음이 들리게), 보고서 빈칸(팀 표, 3.4·3.5, 요약·결론), 슬라이드, 리허설.

### 7.2 애매해서 설명이 필요한 것

| 무엇 | 왜 애매한가 | 어떻게 설명하나 |
|---|---|---|
| E와 N의 길이가 다름 (aha 3.5 vs 2.6 s, failure 3.7 vs 2.0 s) | 과제는 길이를 같게 하라고 하지 않았지만 비교 공정성 질문이 나올 수 있다 | N은 같은 기능 동작을 일정 속도로 하는 것이라 생각·반응 구간이 없어서 짧다 |
| aha의 응시 시각이 E와 N에서 다름 | 나란히 영상에서 두 응시가 겹치지 않는다 | E는 생각·깨달음 뒤에 응시한다(설계 의도). 비교 영상을 보여 줄 때 말로 짚는다 |
| 진폭비가 1보다 큼 (failure E 1.14) | 오류처럼 보인다 | failure E의 주 채널은 pitch(처짐)다. 측정한 pitch 범위가 명령보다 14 % 컸다는 뜻이고 오류가 아니다. 더 처졌는지 더 움찔했는지는 결과 탭 그래프로 확인한다(이유는 확인하지 않았다). 반대로 숙인 채 하는 도리질(yaw ±10°)은 진폭비 0.67–0.68로 덜 실행됐다 [M] |
| 지연에 `(r² 0.38)`처럼 낮은 r²가 붙음 | 숫자를 믿어도 되나 | r² < 0.9인 지연은 참고만 한다. 판정에도 쓰지 않는다 |
| 한계 지도에서 Neutral의 계산 가속이 큼 | 느린 모션인데 가속이 크다 | linear는 시작·끝에서 속도가 계단처럼 바뀌어 계산 가속이 크게 나온다(이론상 무한대). 실제 위험이 아니다 |
| R3 범위(속도 비 ≤ 0.22)가 aha E(0.386)·success E(0.372)보다 느림 | "R3가 괜찮았으니 aha도 안전"이라고 쓰기 쉽다 | 그렇게 쓰지 않는다. 두 모션은 R2 실측 자체가 근거다 |
| Expressive vs Neutral 추종 지표 | "Expressive가 더 표현적"의 증거처럼 보인다 | 추종 지표는 "명령을 얼마나 따라갔나"이고 표현력이 아니다 |
| roll 부호, 안테나 처짐 방향 | 실제 로봇에서 따로 확인하지 않았다 | 촬영본에서 failure의 기울어짐과 안테나 처짐이 설계대로 보이는지 확인해 한 줄 적는다 |

### 7.3 한계 (보고서 '한계'에 쓸 것)

- 사람 평가가 없다. V/A와 의도한 읽힘은 설계 목표다. 평가를 한다면 이름·조건이 안 보이는 영상을 무작위 순서로 보여 주고, 의도를 먼저
  고르게 한 뒤 V/A를 묻는다([09] 방식). 지금 영상에는 모션 이름이 찍혀 있어 그대로 쓰면 안 된다.
- 효과음은 효과음처럼 들린다(earcon). 사람 평가 없이 V/A 규칙으로만 만들었다.
- 머리 추종의 데드밴드·지연은 SDK에 고정된 P 제어 때문이다. 게인을 바꿔 확인하지 않았다.
- MuJoCo는 실제 로봇보다 훨씬 낙관적이다(모터 속도·토크 포화 없음). 시뮬레이션 값을 실제 로봇 예측으로 쓰지 않았다.
- 모터 오류 레지스터를 읽을 수 없어 motor error는 사람 관찰에 의존한다.
- 반복 횟수가 적다(시행당 1–6회). 로봇 1대.
- macOS·Linux 실행은 확인하지 않았다.

### 7.4 예상 질문

| 질문 | 답 |
|---|---|
| V/A를 측정했나? | 아니다. 설계 목표다([09] 형식에 맞춤). |
| 왜 2°는 안 움직이나? | P 제어만 쓰는 머리 모터의 데드밴드. IK가 요구한 관절 변화가 0.6°인데 관절이 0° 움직였다 [M]. |
| 왜 0.19 s 늦나? | 같은 P 제어 특성. 안테나는 68 ms라 명령 경로 문제가 아니다. |
| SDK가 한계 밖 명령을 막나? | 막지 않는다. IK가 실패하면 직전 목표에 조용히 멈춘다. 그래서 우리 도구가 실행 전에 계산 검사를 한다. |
| cartoon은 왜 위험한가? | 피크 속도가 linear의 5.6배이고 명령이 목표를 10 % 넘어간다. 짧은 cartoon이 하드웨어 한계에 가장 가깝다. |
| Neutral에는 왜 소리가 없나? | 과제 조건이다(안테나 움직임·소리 없음). |
| 왜 시뮬레이션 결과를 예측에 안 쓰나? | MuJoCo는 모터 포화를 모델링하지 않는다. 같은 램프에서 실제 로봇보다 훨씬 잘 따라갔다. |
| 어디서 무너졌나? | (R3 D 0.3 → 0.2 결과로 채운다) |

---

## 8. 교수님께 제출할 것

### 8.1 제출물

| 제출물 | 만드는 곳 |
|---|---|
| 짧은 보고서 (한국어 가능, 팀원 이름·학번·개인 기여 포함) | [HW4_REPORT_DRAFT.md](docs/report/HW4_REPORT_DRAFT.md) → 최종 문서 (PDF 권장) |
| 소스 코드 + 설치·실행 방법 | 아래 8.2의 zip (README에 설치·실행 방법이 있다) |
| 짧은 시연 영상: Expressive·Neutral, 한계 시험 | 촬영본 편집 (TEAM_GUIDE §5) |

### 8.2 소스 zip 만들기 (제출 직전)

```
.venv\Scripts\python tools\make_submission.py          (Windows)
.venv/bin/python tools/make_submission.py              (macOS·Linux)
```

- 결과: `dist/reachy_hw4_source_<날짜>.zip` (약 150개 파일, 몇 MB). `dist/`는 git에 올라가지 않는다.
- `--list`: 들어갈 파일만 보여 준다. `--test`: zip을 임시 폴더에 풀어 그 사본에서 자동 테스트를 돌린다(몇 분).
- `--with-data`: 실제 로봇 측정 세션(`results/lab/*_robot_R1|R2|R3`)도 넣는다. 교수님이 데이터를 요구할 때만.

### 8.3 들어가는 것과 빠지는 것

| 들어감 | 이유 |
|---|---|
| `README.md`, `pyproject.toml`, `constraints.txt` | 설치·실행 방법과 정확한 버전 |
| `setup_windows.bat`·`run_gui.bat`, `setup_mac.command`·`run_gui.command`, `setup_linux.sh`·`run_gui.sh` | 더블클릭 설치·실행 |
| `reachy_motion/` | 코드 전체 (GUI, 모션 엔진, 안전 검사, 실행기, 분석) |
| `motions/` | 확정 모션 8개(설정값이 코드에 그대로), 효과음, 이전 버전·후보(테스트가 읽는다) |
| `tests/` | 자동 테스트 (네트워크·로봇 없이) |
| `docs/TEAM_GUIDE.md`, `docs/lab/GUI_ROBOT.md`, `docs/lab/MOTION_LAB.md`, `docs/lab/screenshots/v3_*.png` | GUI `? 사용법` 버튼이 여는 설명서(테스트도 읽는다) |

| 빠짐 | 이유 |
|---|---|
| `results/` | 측정·계산 결과는 보고서에 그림·표로 들어간다 (필요하면 `--with-data`) |
| 나머지 `docs/` (보고서 초안, 발표 구성안, 분석 문서) | 팀 내부 자료. 내용은 보고서에 들어간다 |
| `HANDOVER.md`, `CLAUDE.md`, `tools/` | 팀·개발 도구용 |
| `.venv/`, 캐시, `dist/` | 각 PC에서 다시 만든다 |

---

## 9. git으로 같이 작업하기

### 9.1 기본 명령

```
git pull                                  # 작업 전에 항상 최신으로
git status                                # 바뀐 파일 보기
git add results/lab/<세션 폴더>            # 올릴 것만 고른다
git commit -m "R2 neutral 3개 실측"
git push
```

- push하려면 저장소 주인이 GitHub `Settings → Collaborators`에서 초대해야 한다. git이 낯설면 GitHub Desktop을 써도 된다.
- 보고서·슬라이드는 git보다 공유 문서(구글 문서 등)에서 같이 쓰는 편이 충돌이 없다. 마지막 본만 저장소에 넣어도 된다.
- 휴대폰 영상은 크다(GitHub은 파일당 100 MB 제한). 영상은 공유 드라이브에 둔다.
- 같은 문서를 두 사람이 동시에 고치지 않는다.

### 9.2 저장소에 올리지 않는 것 (`.gitignore`)

| 안 올림 | 이유 |
|---|---|
| `.venv/`, 캐시, `dist/`, `*.zip` | 각 PC에서 다시 만든다 |
| `results/lab/exports/`, `results/lab/videos/` | GUI가 언제든 다시 만든다 |
| `results/lab/*_robot_connection/`, `results/phase4/r0/`, `results/lab/sim_daemon_logs/`, 모든 `results/**/*.log` | 연결할 때마다 생기는 기록, daemon 로그 |
| `results/lab/*_mock_*`, `results/phase2/runs·sim_runs·exports`, `results/phase1/probes/`, 옛 MuJoCo 영상 3개(수정 3차 전 확정 모션 영상 포함) | 테스트용·중간 산출물 |
| 개발 기록 문서(개발 계획, 검증 기록, CLI 실기기 절차, 옛 화면 캡처) | 팀원이 볼 필요 없음. 개발 PC에만 있다 |

코드 주석에 나오는 문서 중 일부(`docs/phase4/PHASE4_PLAN.md`, `docs/VERIFICATION.md` 등)는 위 이유로 저장소에 없다.

**실제 로봇 측정 세션(`results/lab/<시각>_robot_R1|R2|R3`)과 MuJoCo 세션은 올린다.** 새로 잰 세션도 `git add`로 올려 팀이 같이 분석한다.

---

## 10. 안전 (요약, 자세한 것: TEAM_GUIDE §2, [GUI_ROBOT.md](docs/lab/GUI_ROBOT.md))

- 한 로봇 = 한 프로그램. 대시보드 앱·다른 PC·CLI로 동시에 조작하지 않는다(SDK에 잠금이 없다).
- 로봇 옆에 한 명: 머리를 받칠 준비, 전원 스위치에 손이 닿게.
- 이상(떨림·뜨거움·이상한 소리·모터 오류)이 보이면 `■ 정지` → 머리를 받치고 `토크 OFF` → 그래도 안 되면 전원.
- 새 조건은 MuJoCo에서 먼저, 작고 느리게, 한 번에 한 설정만. R3는 한 단계씩.
- `토크 OFF`를 누르면 머리가 내려간다. 반드시 받친다. `연결 끊기`와 창 닫기는 토크를 끄지 않는다.
- 로봇은 손상 없이 반납한다.
- AI 코딩 도구를 쓴다면: 저장소의 `CLAUDE.md` 규칙대로 **AI 도구가 실제 로봇을 움직이게 하지 않는다**. 로봇 버튼은 사람이 누른다.

---

## 11. 문서 지도

| 문서 | 언제 |
|---|---|
| [README.md](README.md) | 설치·실행 요약 (교수님 제출 zip에도 들어감) |
| [docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md) | GUI 사용법, 실험 순서, 촬영, 분석, 문제 해결 |
| [docs/report/SUBMISSION_CHECKLIST.md](docs/report/SUBMISSION_CHECKLIST.md) | 과제 요구사항별 상태 |
| [docs/report/HW4_REPORT_DRAFT.md](docs/report/HW4_REPORT_DRAFT.md) | 보고서 초안 |
| [docs/report/PRESENTATION_OUTLINE.md](docs/report/PRESENTATION_OUTLINE.md) | 발표 구성안 |
| [docs/phase3/MOTION_REPORT_TABLE.md](docs/phase3/MOTION_REPORT_TABLE.md) | 보고서용 모션별 전체 표, 참고 논문 요약 |
| [docs/phase2/MOTION_DESIGN.md](docs/phase2/MOTION_DESIGN.md), [MOTION_SPECS.md](docs/phase2/MOTION_SPECS.md) | 설계 규칙, 키프레임 사양표 (computed) |
| [docs/phase3/MOTION_REVISIONS.md](docs/phase3/MOTION_REVISIONS.md), [BOREDOM_CANDIDATES.md](docs/phase3/BOREDOM_CANDIDATES.md), [MUJOCO_REVIEW.md](docs/phase3/MUJOCO_REVIEW.md) | 설계 과정의 근거 |
| [docs/lab/GUI_ROBOT.md](docs/lab/GUI_ROBOT.md) | 실제 로봇 버튼·순서·알려진 제한·효과음 |
| [docs/lab/MOTION_LAB.md](docs/lab/MOTION_LAB.md) | GUI 전체 설명, 기록 파일 형식 |
| [docs/phase1/SDK_ANALYSIS.md](docs/phase1/SDK_ANALYSIS.md), [SOURCE_REFERENCES.md](docs/phase1/SOURCE_REFERENCES.md) | SDK 분석과 소스 근거 |
| [docs/phase4/STARTUP_STOP.md](docs/phase4/STARTUP_STOP.md) | 연결·기동·정지 안전 분석 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 코드 구조 |
| [motions/sounds/README.md](motions/sounds/README.md) | 효과음 파일과 규칙 |
| [CLAUDE.md](CLAUDE.md) | AI 개발 도구용 규칙과 SDK 동작 메모 |

막히면: 이 문서 §7.4 → TEAM_GUIDE §9 문제 해결 → 개발 담당에게 화면·오류 캡처와 `results/lab`의 해당 세션 폴더 이름을 보낸다.
