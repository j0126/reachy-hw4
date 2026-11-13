# Phase 3-1: MuJoCo 검증과 사용자 검토 준비 (2026-11-10)

모션 초안 8개(`motions/*.yaml`, 수정 없음)를 로컬 MuJoCo(127.0.0.1, headless)에서 한 세션으로 모두 실행했다.
상세 표(시작·종료 자세, 키프레임, 비교, 궤적 검사): `results/phase3_sim/review/20261110_233427/review.md`(자동 생성),
원자료: 같은 폴더의 `summary.json`, `runs/<motion>/{commands,present_simulated,ticks}.csv`.
다시 만들기: `.venv\Scripts\python -m reachy_motion sim-verify` (`--viewer`로 창을 띄워 함께 볼 수 있음).

**미검증 — 반드시 감안할 것**: 안테나 방향(droop = right −/left +, perk = 0° 쪽)은 SDK sleep 자세에서 **추론**한 것이고,
**roll 부호**는 실기기에서 확인하지 않았다. MuJoCo 모델도 같은 정의를 쓰므로 sim에서 맞아 보여도 실기기 검증이 아니다.

## 결과 요약

> 아래 표는 2026-11-10의 초안(v0) 결과다. 2026-11-11 수정 1차(aha expressive, boredom) 뒤 다시 실행한 결과는
> `docs/phase3/MOTION_REVISIONS.md` §MuJoCo 확인과 `results/phase3_sim/review/20261111_171914/`에 있다.
> 8개 모두 완료됐고, 종료 오차 ≤ 0.10°, 측정 최소 관절 여유 27.0–41.2°였다.

| 모션 | MuJoCo 실행 | 측정 종료 오차 (rest 대비) | 측정 최소 관절 여유 | 계획 검사 (초기 정책) |
|---|---|---|---|---|
| aha_recommend E / N | 완료 / 완료 | ≤ 0.10° · 0.10 mm · 안테나 0.01° | 31.0° / 33.9° | 통과 (여유 28.9° / 33.8°, Stewart 속도 비 0.32 / 0.02) |
| boredom E / N | 완료 / 완료 | 〃 | 37.1° / 30.0° | 통과 (37.2° / 30.0°, 0.07 / 0.01) |
| success E / N | 완료 / 완료 | 〃 | 31.9° / 39.4° | 통과 (29.4° / 37.1°, 0.37 / 0.02) |
| failure E / N | 완료 / 완료 | 〃 | 39.8° / 41.2° | 통과 (38.0° / 40.2°, 0.10 / 0.01) |

- 모든 실행이 정지 상태에서 시작(정지 판정: 0.3 s 동안 관절 변화 < 0.03°), 측정 시작 오차 ≤ 0.10°. tick은 8개 모두 건너뜀 0,
  ≈ 50.0 Hz(pc_measured).
- 계획 궤적 검사(computed): IK NaN 0, 관절 여유 ≥ 28.9°, Stewart 속도 비 ≤ 0.37, 몸통 0, 안테나 ≤ 0.18, 포락선 안. 경고는
  예상된 것뿐(cartoon 외삽, neutral의 LINEAR 속도 계단, 초안 표시). 통과 = 초기 정책 안, 기구적 안전 보장 아님.
- Expressive vs Neutral: 4쌍 모두 계획상 같은 시작·종료(비교 문제 0), 측정 시작·종료 차 ≤ 0.20°. neutral의 기본 동작(키별 회전
  변화의 주 축·부호·크기 0.5–2배)이 expressive 안에 모두 있다 — aha: present yaw +22, boredom: glance-away yaw +25,
  success: 끄덕임 pitch +10, failure: 도리질 yaw ±12(expressive는 고개를 숙인 채 ±10).
- 측정 오차가 작은 것은 동작 뒤 1 s 유지 + 정지 대기 후에 쟀기 때문이다. 움직이는 동안의 추종(지연·진폭)은 이번 범위가 아니다.

## 시작 자세 안전 예외 (sleep → rest)

MuJoCo는 sleep 자세(측정 z −50.3 mm, pitch 23.5°, 안테나 ±174.7°)에서 시작한다. SDK가 sleep에 실제로 보내는 관절값
(`SLEEP_HEAD_JOINT_POSITIONS`)은 stewart_1·2·5·6을 URDF 한계 **밖으로 0.8–9.5°** 보낸다(새로 확인한 사실, computed).
그래서 시작 램프만 예외로 하되 `safety/startup.py`에서 규칙을 좁혔다:

- 관절마다 따로: 여유가 시작보다 나빠지면 안 됨(바닥 = min(10°, 시작 여유 − 0.25°)). 이전 구현은 6개 관절에 가장 나쁜
  시작 여유 하나를 바닥으로 써서, joint-space sleep에서 출발하면 ±30° roll·pitch 모서리 램프까지 통과시켰다(확인함) → 수정.
- 포락선(x·y·z·roll·pitch·yaw·안테나)은 시작값이 이미 밖에 있는 쪽으로만, 시작값까지만 넓힌다.
- 속도·IK NaN·ψ wrap 등은 완화하지 않고, 램프 끝 자세는 정상 정책을 통과해야 한다.
- 테스트 `tests/test_startup_ramp.py`(9): sleep→rest 통과, 한계 근처 목표·관절별 바닥 위반·과속·z 더 내려감·IK NaN·안테나
  과회전은 거부, 정상 시작에서는 완화 없음.

## 눈으로 검토하기

```
.venv\Scripts\python -m reachy_motion sim-play aha_recommend --variant expressive
.venv\Scripts\python -m reachy_motion sim-play aha_recommend --variant neutral
.venv\Scripts\python -m reachy_motion sim-play boredom --variant expressive
.venv\Scripts\python -m reachy_motion sim-play boredom --variant neutral
.venv\Scripts\python -m reachy_motion sim-play success --variant expressive
.venv\Scripts\python -m reachy_motion sim-play success --variant neutral
.venv\Scripts\python -m reachy_motion sim-play failure --variant expressive
.venv\Scripts\python -m reachy_motion sim-play failure --variant neutral
```

boredom 후보 3종(scan·story·doze, 2026-11-11): `sim-play boredom --dir motions\candidates\boredom_<후보>` —
설명·키프레임·검사 결과는 `docs/phase3/BOREDOM_CANDIDATES.md`.

재생 후 Enter = 다시, v = 같은 모션의 다른 변형(바로 비교), r = YAML을 고친 뒤 다시 읽어 재생, q = 종료.
수정은 `motions/<name>.<variant>.yaml`을 직접 고치거나 `python -m reachy_motion gui`에서 한다. 고친 뒤
`python -m reachy_motion check <name> --variant both`로 정책·비교 조건을 확인한다.

## 영상으로 보기 (명령 하나로 전부, 2026-11-11)

```
.venv\Scripts\python -m reachy_motion video
```

`motions/`의 4쌍과 `motions/candidates/*/`의 후보를 모두 expressive와 neutral을 나란히 놓아 렌더링한다.
결과는 `results/phase3_sim/videos/<시각>/`에 저장된다.

- `<이름>.mp4`: 쌍마다 영상 하나(H.264). `--format webp`이면 애니메이션 WebP, `both`면 둘 다 만든다.
- `index.html`: 더블클릭하면 브라우저에서 모든 영상이 재생된다.
- `manifest.json`: 명령·파라미터·data_kind·종료 오차.

옵션은 `--name boredom`, `--dir motions\candidates\boredom_scan`, `--size 560x420`, `--fps 25`, `--tail 1.5`다.

**방식**: daemon 없이 SDK sim과 같은 MuJoCo 모델·2 ms 스텝·50 Hz 명령을 **시뮬레이션 시간**으로 재생하고, 화면 밖 카메라로
렌더링한다. 명령은 `ctrl[:7]` = IK 관절, `ctrl[-2:]` = −안테나다(`reachy_mini/daemon/backend/mujoco/backend.py:83-91, 257-260`).
초기 정책을 통과한 모션만 재생한다. 구현은 `reachy_motion/sim_video.py`다.

**sim-play와의 차이와 한계**:
- 실시간 계수(이 PC ≈ 0.8–0.86)와 PC 지터가 없어서 설계한 속도 그대로 보인다.
- 그래도 data_kind는 simulated다. MuJoCo 머리는 명령보다 늦게 따라간다. 예를 들어 15°를 0.6 s에 돌리면 최대 약 6° 차이가 난다
  (`index.html`의 'max sim-command gap'). 정지 후에도 천천히 수렴해서, 1 s 뒤 ≈ 0.3°, 3 s 뒤 ≈ 0.03°다.
- 실기기 예측이 아니다.

**형식과 보기**:
- 기본 형식은 MP4다(H.264 High, yuv420p, 25 fps, 쌍당 0.2–0.5 MB). 인코더는 PyAV `av==19.0.1`에 들어 있는 libx264다.
  - 2026-11-11에 uv 캐시에서 오프라인으로 설치했고 `constraints.txt`에 고정했다. SDK 3종 버전은 그대로다(`env` → pins OK).
  - SDK에서 `av`를 import하는 곳은 `reachy_mini/media/central_consumer.py`뿐이다. 그 모듈은 아무도 import하지 않으므로 sim
    동작은 바뀌지 않는다.
  - PyAV가 없으면 `auto`는 애니메이션 WebP로 대신 만든다.
- 앱 미리보기는 `.claude/launch.json`의 `motion-videos`다(127.0.0.1:8765 정적 파일 서버, 이 PC에서만 접속 가능).

## 검토 기록표 (직접 채우기)

| 모션 | 의도가 읽히나 (1–5) | 느껴진 valence (−2…+2) | 느껴진 arousal (−2…+2) | 자연스러움 (1–5) | E와 N 차이가 분명한가 | 수정할 점 (키 라벨·값) |
|---|---|---|---|---|---|---|
| aha_recommend E | | | | | | |
| aha_recommend N | | | | | | |
| boredom E | | | | | | |
| boredom N | | | | | | |
| success E | | | | | | |
| success N | | | | | | |
| failure E | | | | | | |
| failure N | | | | | | |

## 한계

- MuJoCo는 마찰 지배적이고 이 PC에서 실시간보다 느리다(Phase 1 §5.5) — 속도감·작은 동작은 실기기와 다를 수 있다.
- viewer 모드는 daemon이 25 Hz 카메라 렌더링과 127.0.0.1 RTP 스트림도 띄워 더 느릴 수 있다.
- 움직이는 중 추종 성능(지연·RMSE·Peak)은 아직 분석하지 않았다(원자료는 저장됨).
- 실기기 확인은 학생의 최종 설계 확정 후 별도 승인(Phase 4)으로만 한다.
