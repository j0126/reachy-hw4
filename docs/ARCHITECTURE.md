# 아키텍처 (Phase 0 설계 → Phase 2 구현)

> 상태: Phase 1에서 `analysis/`(7개 모듈), `backends/sim_daemon.py`, `cli.py`, `sdk_env.py`를, Phase 2에서 모션 엔진
> (`library/`, `planner.py`, `timeline.py`, `safety/`, `executor/`, `backends/{base,mock,sdk,daemon_client}.py`, `service.py`),
> `util/`(HW3 복사), Motion Editor GUI(`gui/`), Phase 2 CLI(`cli_phase2.py`)를 구현했다. Phase 0 설계와 달라진 점은 §4 끝에 정리했다.
> SDK 동작에 대한 근거는 [phase1/SDK_ANALYSIS.md](phase1/SDK_ANALYSIS.md) (SDK 1.11.0, 파일:줄).

## 1. 설계 목표

1. **HW4 요구 충족** — A/B/C × {Expressive, Neutral}, 파라미터(keyframe·duration·amplitude·interpolation·pause)를
   데이터로 관리, V/A·의도·애니메이션 원리 메타데이터를 스펙에 포함.
2. **같은 API로 Mock / MuJoCo / 실기기** 실행 — 기본은 Mock·MuJoCo, 실기기는 명시적으로 "arm" 해야만 생성.
3. **실행 전 안전검사** — IK 실패, 관절 제한, 요구 모터 속도, 오버슈트(cartoon)까지 계획 단계에서 거른다.
   SDK는 IK 실패 시 **조용히 직전 목표를 유지**하므로(분석 §4) 계획 단계 검사가 필수다.
4. **명령값과 실측값을 같은 시계로 기록** → RMSE·Peak Error·Lag, 모터 사양 대비 분석.
5. **Term Project FSM에 그대로 연결** — 비차단 재생, 취소, 우선순위 선점, idle 동작.

## 2. 계층 구조

```
 FSM (Reachy Café) / CLI / tests
          │  play(name, variant, intensity, priority) → MotionHandle      ▲ 이벤트(started/finished/cancelled/violation)
          ▼                                                                │
 ┌──────────────────────┐     ┌──────────────────────┐
 │ MotionService (facade)│────▶│ Motion Library        │  MotionSpec 레지스트리 (A/B/C × variant), 파라미터 오버라이드
 └──────────┬───────────┘     └──────────────────────┘
            │ spec
            ▼
 ┌──────────────────────┐     ┌──────────────────────┐
 │ Planner (compile)     │────▶│ Safety Checker        │  정적 검사: IK·관절 제한·속도·가속도·작업공간
 │ spec → Timeline       │◀────│ (SafetyReport)        │
 └──────────┬───────────┘     └──────────────────────┘
            │ Timeline (SI 단위, 시간 표본)
            ▼
 ┌──────────────────────┐
 │ Motion Executor       │  전략: StreamStrategy(set_target) | GotoStrategy(goto_target)
 │ + Runtime Guard       │  실행 중 감시: 명령-측정 편차, daemon 오류, 취소
 └──────────┬───────────┘
            │ Backend 프로토콜
   ┌────────┼──────────────────────────┬──────────────────────────────┐
   ▼        ▼                          ▼                              │
 Mock   SdkBackend(sim)          SdkBackend(robot)                    │
 (daemon 없음)  localhost daemon --sim   network, armed=True 필수       │
            │                                                          │
            ▼                                                          │
 ┌──────────────────────┐   ┌──────────────────────┐                  │
 │ Telemetry Recorder    │──▶│ Analysis / Reports    │  RMSE·Peak·Lag, IK 기반 모터각·속도 vs 사양, 그림
 │ commanded + measured  │   │ (analysis.metrics …)  │                  │
 └──────────────────────┘   └──────────────────────┘                  │
```

## 3. 디렉터리 구조 (목표)

```
reachy_hw4/
├── CLAUDE.md  README.md  pyproject.toml  .gitignore
├── docs/
│   ├── DEVELOPMENT_PLAN.md  ARCHITECTURE.md  VERIFICATION.md  HW3_REUSE.md
│   └── phase1/  SDK_ANALYSIS.md  SOURCE_REFERENCES.md
├── motions/         <name>.<variant>.yaml — 편집 가능한 확정 모션 8개(도·mm)                [P2]
├── reachy_motion/
│   ├── __init__.py  __main__.py  cli.py  sdk_env.py          [P0–P1 ✅]
│   ├── cli_phase2.py  specs/check/play/sim-play/timing/export/approval-template/gui/phase2   [P2]
│   ├── analysis/    interpolation.py goto_replay.py metrics.py figures.py
│   │                limits.py motor_demand.py sim_smoke.py                  [P1 ✅]
│   ├── library/     pose.py(SI Pose6, RobotState) spec.py(트랙별 키) io.py(YAML/JSON) compare.py registry.py   [P2]
│   ├── planner.py   timeline.py(Timeline, PreparedMotion)                    [P2]
│   ├── safety/      policy.py(초기 정책) checker.py approval.py(Phase 4 승인 게이트)   [P2]; guard.py(실행 중 감시) [P3]
│   ├── executor/    clock.py timing.py(tick 시각·지터) executor.py          [P2]
│   ├── backends/    sim_daemon.py                                            [P1 ✅]
│   │                base.py mock.py sdk.py(sim: MuJoCo 인터록 / robot: 승인 게이트) daemon_client.py(GET 전용)   [P2]
│   ├── service.py   MotionService (FSM facade)                               [P2]
│   ├── gui/         model.py plots.py playback.py (Qt 없음) app.py (PySide6)  [P2]
│   ├── util/        platform_timing.py event_logger.py tables.py (HW3 그대로 복사)   [P2]
│   └── telemetry/   recorder.py store.py tracking.py motor_limits.py         [P3]
├── tests/           unittest, 하드웨어 없이 전부 실행 (GUI는 offscreen Qt)
└── results/         phase1/ phase2/ phase3_sim/ phase4_robot/  (+ manifest.json)
```

의존 방향: `gui / cli → service → library, planner, safety, executor → backends, telemetry → analysis`.
`library`는 SDK를 import하지 않는 순수 데이터(→ 테스트·문서화 쉬움; `Easing`도 라이브러리의 일반 enum). SDK import는 `backends`,
`safety`(IK), `planner`(`Easing` → `InterpolationTechnique` 매핑 후 `time_trajectory` 호출), `analysis`로 한정한다.
`gui`는 엔진을 호출하는 별도 계층이다: `model`·`plots`·`playback`은 Qt 없이 테스트되고, `app`만 PySide6를 쓴다.

## 4. 핵심 데이터 타입 (P2에서 구현할 계약)

```python
@dataclass(frozen=True)
class Pose6:                       # 중립 자세 기준, SI 단위
    x: float = 0; y: float = 0; z: float = 0          # m
    roll: float = 0; pitch: float = 0; yaw: float = 0  # rad — create_head_pose(..., degrees=False) ("xyz"; 기본값은 degrees=True)

@dataclass(frozen=True)
class Keyframe:
    duration: float                # 이전 키프레임에서 여기까지 이동 시간 (s)
    head: Pose6
    antennas: tuple[float, float]  # rad [right, left]
    body_yaw: float                # rad — goto_target 기본값 0.0 함정 때문에 항상 명시
    easing: Easing                 # 라이브러리 enum: SDK 4종에 대응하는 값 + 사용자 정의(예: anticipation 파라미터); planner가 SDK로 매핑
    hold: float = 0.0              # 도착 후 정지(pause) 시간 (s)

@dataclass(frozen=True)
class MotionSpec:
    name: str                      # "aha_recommend" | "boredom" | "success" | "failure"
    variant: Literal["expressive", "neutral"]
    keyframes: tuple[Keyframe, ...]
    intent: str                    # 전달 의도 (문서화)
    valence: float                 # [-1, 1]
    arousal: float                 # [-1, 1]
    principles: tuple[Principle, ...]   # anticipation, follow-through, slow-in/out, timing, exaggeration, …
    params: Mapping[str, float]    # amplitude_scale, tempo_scale 등 (스윕 실험용)

@dataclass
class Timeline:                    # Planner 출력 = 실행기가 보낼 명령의 단일 진실 원천
    t: np.ndarray                  # s, 단조
    head: np.ndarray               # (N, 4, 4)
    antennas: np.ndarray           # (N, 2) rad
    body_yaw: np.ndarray           # (N,) rad
    segment: np.ndarray            # (N,) 키프레임 인덱스 (분석·라벨용)
```

**Phase 2 구현에서 달라진 점** (코드가 기준: `library/spec.py`, `timeline.py`, `safety/policy.py`, `backends/base.py`)

- `Keyframe` 하나 대신 **트랙별 키**: `HeadKey(duration, pose: Pose6, easing, hold, label)`, `AntennaKey(…, antennas)`,
  `BodyKey(…, yaw)`. 트랙은 t = 0에서 함께 시작하고 각자 진행한다(끝난 트랙은 마지막 값 유지). SDK goto는 모든 채널에 같은 s를
  쓰므로(Phase 1 §3.4) follow-through·overlapping action 같은 채널 간 시차는 트랙 분리로만 표현할 수 있다.
- `MotionSpec`에 `amplitude_scale`·`tempo_scale`(planner가 적용하는 전역 편집 노브, 키는 설계값 그대로 유지),
  `sound: SoundCue | None`(Phase 2는 메타데이터만, neutral은 없음), `draft: bool`(학생이 확정하기 전 초안), `start: RobotState`
  (기본 `REST`)가 추가됐다. `effective()`가 실제 실행 파라미터(배율 적용 키)를 돌려준다. `digest()`는 승인·로그를 정확한 스펙에 묶는다.
- 모션은 Python 카탈로그가 아니라 **`motions/<name>.<variant>.yaml`**(도·mm, 단위 접미사)로 저장하고 `library/io.py`가 SI로 바꾼다.
- `Timeline`은 트랙별 키 인덱스(`head_key`, `antenna_key`, `body_key`)와 `digest()`를 갖고, `PreparedMotion(timeline, report)`는
  보고서가 **그 타임라인 다이제스트**에 대한 것이고 정책을 통과했을 때만 `runnable`이다. 실행기는 `PreparedMotion`만 받는다.
- 안전검사는 `SafetyPolicy`(초기 정책 임계값) → `SafetyReport`(위반·경고·지표 + 면책 문구, `data_kind="computed"`).
- `Backend`는 `set_target`/`goto_target`에서 head·antennas·body_yaw를 **항상 함께** 받는다(`check_command`가 `body_yaw=None` 거부).

## 5. 모듈 책임

| 모듈 | 책임 | 비고 |
|---|---|---|
| `library` | MotionSpec 정의, 레지스트리, 파라미터 오버라이드, V/A·원리 메타데이터 | SDK 비의존 |
| `planner` | spec → Timeline (기본 100 Hz 표본). 보간은 **SDK `time_trajectory`를 그대로 호출**해 SDK 4종과 동일 프로파일 보장 | 사용자 정의 이징은 별도 표기 |
| `safety.limits` | SDK 자산(`hardware_config.yaml`, URDF/MJCF)과 IK 래퍼(160°/65°)에서 한계 로드 | 출처 줄 번호 보존 |
| `safety.checker` | Timeline 전 표본 IK → NaN·관절 제한 여유·요구 속도/가속도·작업공간·오버슈트 검사 | 위반 시 실행 거부 |
| `safety.guard` | 실행 중 명령-측정 편차, daemon 오류 감시 → 중단·중립 복귀 | P3 |
| `executor` | Timeline 재생, 명령 로그(보낸 그대로), 취소·선점 | 전략 두 가지(§6) |
| `backends.base` | `connect/close/present/set_target/goto_target/capabilities`, `data_kind` | capabilities 예: `torque_control`(MuJoCo는 없음 — 모드가 항상 enabled), `imu`, `daemon_stats` |
| `backends.mock` | daemon 없이 결정론적 모델(50 Hz ZOH; 머리·몸통은 IK 후 +1 tick, 안테나는 다음 tick(+0) — 실기기·mockup 구조, MuJoCo 모드는 둘 다 같은 tick; + 1차 지연) | 단위 테스트용 |
| `backends.sdk` | `reachy_mini.ReachyMini` 래퍼. sim: `connection_mode="localhost_only"`; robot: `armed=True` 없으면 생성 거부 | |
| `telemetry` | 명령·측정 동기 기록(단조 시계), CSV+manifest, 추종 지표 | P3 |
| `service` | FSM용 비차단 API, 단일 실행 스레드, 우선순위 선점, idle 동작 | P2 |

## 6. 실행 전략 (Phase 1 분석에 근거)

| | GotoStrategy (`goto_target` 체인) | StreamStrategy (`set_target` 스트리밍) |
|---|---|---|
| 보간 위치 | daemon `play_move` 100 Hz | 클라이언트 Planner (같은 `time_trajectory`) |
| 명령 로그 | daemon 내부라 보이지 않음 → `analysis.goto_replay`로 재구성 | 보낸 값 그대로 기록 (정확) |
| 세그먼트 경계 | 각 goto가 **측정 자세**에서 시작, 완료 응답 대기 → 키프레임 사이 간극 | 연속 |
| 끝점 | LINEAR는 g/D 미달(g = 마지막 간격, 공칭 10 ms 이상) | Planner가 마지막 표본을 정확히 목표로 |
| 위험 | `body_yaw` 기본 0, 다른 move 실행 중이면 무시됨 | WiFi 지연·지터가 목표 갱신 간격에 그대로 반영 |
| 용도 | SDK 보간법 자체를 평가·비교하는 실험 | 표현적 모션 기본 재생, 추종 성능 분석 |

기본값은 **StreamStrategy**, SDK 보간 비교 실험은 GotoStrategy. 최종 결정과 근거는 Phase 1 보고서 §7.

## 7. FSM 통합 계약 (Term Project)

```python
service = MotionService(backend, library=default_library())
h = service.play("aha_recommend", variant="expressive", intensity=1.0,
                 priority=Priority.REACTION, interrupt=True)   # 즉시 반환
h.wait(timeout=5.0); h.cancel(); h.state                       # PENDING/RUNNING/DONE/CANCELLED/REJECTED
service.on_event(callback)                                     # started / finished / cancelled / safety_violation
service.set_idle("boredom", variant="neutral", after_s=10.0)   # 대기 상태 idle 동작
service.stop(blend_to_neutral=True)
```

- 백엔드를 소유하는 **단일 실행 스레드**(SDK 클라이언트 동시 호출 방지; daemon은 다른 move 실행 중 goto를 무시).
- 선점은 표본 경계에서만, 현재 자세 → 새 모션 시작 자세로 짧은 블렌드.
- 안전검사 거부(REJECTED)는 예외가 아니라 상태 + 이벤트로 알린다(FSM이 다른 상태로 넘어갈 수 있게).

## 8. 실기기 안전 설계

- 백엔드 연결 직후 공통 초기화: `set_automatic_body_yaw(True)` 명시·기록(데몬 전역 플래그), `disable_wobbling()`,
  `stop_head_tracking()`(둘 다 IK 입력에 오프셋을 합성하므로), daemon `version`·`simulation_enabled`·`/api/kinematics/info` 기록.
- `SdkBackend(target="robot")`는 `armed=True` + 승인 메모 문자열 없이는 생성 불가(Phase 2 테스트로 강제).
- 실행 전: daemon 버전 읽기 전용 확인(1.11.0), 안전검사 통과, 진폭·속도 상한을 실기기용으로 더 낮게.
- 실행 중: Runtime Guard 편차 임계 초과 시 중단; 종료 시 중립 복귀. 비상 정지 절차는 Phase 4 계획에 문서화.
