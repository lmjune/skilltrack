# skilltrack (표시 이름: 마비오라 / MabiAura) 인수인계 문서 (2026-09-20)

새 대화에서 이 프로젝트를 이어갈 때 먼저 읽는 문서. 코드 전체를 읽지 않아도 구조와 판단 근거를 알 수 있게 쓴다.
(ROADMAP.md = 할 일 목록, GUIDE.md = 사용자 가이드, 이 문서 = 현재 구조와 결정 사유)

## 1. 무엇을 만드는가

마비노기(4K, 창모드 전체화면, UI 배율 100%) 화면을 **캡처만** 해서 동작하는 오버레이. 클라이언트에 개입 없음.
- 상태창(버프 목록)을 읽어 알림: 꺼짐 / 켜질 때까지 반복 / 남은 시간 N초 미만 / 연장됨
- 버프 행·스킬 슬롯 이미지를 화면 다른 곳에 확대 표시 (미러)
- **보스 디버프**: 보스 체력바 위 디버프 띠를 읽어 빠진 디버프 목록 표시, 버스트 디버프 알림
- 트레이 앱 + 홈 화면 + 캐릭터별 프로필 + 마스터 스위치(켜기/끄기)
- Python 3.14, PySide6, OpenCV, dxcam. Windows 전용 실행, core/ 는 맥에서 테스트 가능

## 2. 파일 지도

```
core/                    순수 로직 (Qt·파일 I/O 없음, numpy in → dataclass out). 픽스처로 테스트
  grid.py                스킬창 격자 검출. detect_grid_in(full_img, rect) → Grid(xs, ys, w, h)
  rows.py                상태창 행 검출. detect_rows(crop) → RowLayout(rows, sections, pitch, time_right, ...)
  strokes.py             글자 '획' 픽셀 추출 (배경 무관). stroke_masks(bgr) → (white, gray, red)
  status.py              행 파싱. parse_rows(crop, layout) → [RowState(active, has_time, red, name_range, time_img, ...)]
  digits.py              시간 텍스트 읽기. GlyphLib(assets/glyphs.json), read_time(time_img, lib) → TimeRead(seconds, plausible)
  pixelwatch.py          획 자리 판정. make_site / read_site(frame, site) → Reading(state on/off/unknown)
  tracker.py             상태 비교 → 이벤트. Tracker.update(states, secs) → [Event]
  layout_store.py        레이아웃 저장/복원 (profiles/layouts/<pid>.json), verify()
  variants.py            이름 접미어 템플릿 (profiles/variants/<pid>/). "(투안의 노래)" 등
  cooldown.py            스킬 슬롯 쿨타임 판정 (표시용)
  bossbar.py             보스 바 찾기(anchor) + 띠 칸/아이콘/라벨 읽기 + IconLib. read_bar(region, lib, icons) → BarRead
  bosstrack.py           보스 디버프 추적. BossTracker.update(BarRead) → [DebuffEvent], shown() → 표시 목록
  config.py              설정 모델 (profiles/config.json). General / Overlays / Profile(regions, watches, mirror_rows, skill_items, boss_watches)
  paths.py               경로·이름 한 곳: ASSETS(번들)/DATA(exe 옆)/PROFILES/DIAG, VERSION, APP_NAME="마비오라", EXE_NAME="mabiaura"
win/                     Windows 전용
  capture.py             dxcam 래퍼. import 시 DPI 설정을 잡으므로 QApplication 뒤에 import
  window.py              게임 창 찾기, 클라이언트 rect
  session.py             Session: 레이아웃 준비 + process(frame) → Result(states, readings, secs, events, notes). 콘솔·앱 공용. FrameSaver
  boss_session.py        BossSession: 바 영역 프레임 → 읽기 → 추적. bosses.json(띠 보스 기억), 진단 프레임 저장
  app.py                 트레이 앱 본체 (App). run.py 가 이걸 실행
  run.py                 진입점: python win/run.py
  watch.py               개발용 콘솔 감시. --debug 창, --boss / --bossonly / --learn. 하드코딩 rect, 프로필 "_console"
  alert_overlay.py       토스트 알림 창 + EditableOverlay(편집 모드 공통) + 소리
  mirror.py              MirrorItem/MirrorGroup (항목별 독립 창, 개별/그룹 이동·배율)
  status_overlay.py      버프 미러 그룹
  skill_overlay.py       스킬 미러 그룹 (모드 always/cooling/dimmed)
  boss_overlay.py        빠진/곧 끝나는 보스 디버프 목록 창 (하나)
  hotkeys.py             전역 단축키 (GetAsyncKeyState 폴링, 기본 꺼짐)
ui/                      설정 화면 (PySide6, theme.py 로 공통 룩)
  home.py                홈: 캐릭터 카드, 마스터 스위치
  calibrate.py           영역 드래그 (status / skill), 드래그 중 실시간 검출 표시
  watches.py             감시 항목 (행 카드, 알림 옵션, 접미어 변형, 미러 옵션)
  skills.py              스킬 표시 슬롯 선택
  boss.py                보스 디버프: 아이콘 이름(공용) / 감시·재표시·버스트(프로필)
  general.py             일반 설정 (단축키, fps, 소리, 진단 저장, 스크린샷 포함, 부드러운 확대, 아이콘 자동 등록)
  edit_bar.py            배치 편집 툴바
assets/glyphs.json       시간 글자 13개 (0-9, 분, 초, M). 글자당 템플릿 1개
assets/boss_icons/       디버프 아이콘 12×12 png (<id>.png, id = sha1 앞 10자리) + icons.json({id: {name, tags}}) + bosses.json(띠 보스 이름 해시)
assets/sounds/*.wav      기본 알림음 3종 (직접 합성)
assets/fonts/            Pretendard (있으면 로드)
tests/                   pytest. fixtures/ 에 4K 원본 PNG (저장소 밖 백업). fixtures/boss/ 는 850×250 바 영역 + truth.json
```

## 3. 데이터 흐름 (실행 중)

```
tick (초당 fps회)
  full = cap.grab()                     전체 화면 1회 (영역별 grab 금지: dxcam 새 프레임 소비 문제)
  frame = full[상태창 rect]
  skills.update(full)                   스킬 슬롯 잘라 미러 갱신
  boss.process(full[BOSS_RECT])         보스 바 → 띠 → 추적 → 목록/버스트 이벤트
  r = sess.process(frame)
     parse_rows        → 행별 이름/시간 영역
     read_site         → 활성/비활성/모름 (저장된 획 자리 픽셀 색)
     read_time         → 초 (읽히면), 접미어 변형 판정
     tracker.update    → 이벤트 (디바운스·추정 타이머·재동기화)
  mirror.update_from(frame, r), overlay.push(이벤트), boss_ov.update_from(shown)
```

## 4. 게임 그리기 규칙 (실측으로 확정. 코드 판단의 근거)

### 상태창
| 항목 | 규칙 |
|---|---|
| 활성 글자 | 불투명 흰색, **≥250** (스크린샷 255, dxcam 캡처 250~254) |
| 비활성 글자 | **회색 단색 209** (던전 등 일부 상황 127). 반투명 아님. 배경 무관 |
| 1분 미만 시간 | 정확히 (255,0,0). 붉은 이펙트는 G,B ≥ 4 |
| 글자 외곽선 | 배경에 따라 있기도 없기도 → 조건으로 쓰지 않음 |
| 패널 | 반투명. 틴트 때문에 배경은 255가 될 수 없음 → 255 = 글자. 폭 ≈ 300px |
| 렌더링 | 픽셀 단위로 동일. 같은 글자·아이콘·접미어는 프레임이 달라도 완전 일치 |
| 상태창 구조 | 행 pitch 24, 아이콘 16px, 이름 왼쪽·시간 오른쪽 정렬. 고정 섹션 위, 가변 섹션 아래 |
| 이펙트 | 대부분 패널 뒤. 드물게 위에 그려져 글자를 덮음 → 그 프레임은 모름, 타이머가 메움 |

### 보스 바 / 디버프 띠 (실측 24프레임: 기브넨·페타크·공상·찬탈자·제바흐, 어두움/흰 얼음/인벤 창 겹침)
| 항목 | 규칙 |
|---|---|
| **게임 스크린샷 ≠ 실제 화면** | 게임의 스크린샷 기능은 바 글자를 가는 획으로, 실제 화면(dxcam)은 **굵은 획**으로 그린다. 위치·크기·아이콘·라벨 폰트는 같고 글자 모양만 다름 → `%` 템플릿 2종. **픽스처는 반드시 dxcam 저장본**(watch.py `b`, 앱 자동 저장)으로 |
| 바 anchor | 오른쪽 끝 `%` 글자 마스크(14×15)가 고정. 이름 첫 행 text_y, `%` 오른쪽 끝 pct_x1. 바 색(보라/녹/노랑+빨강)은 안 씀 |
| 화면 위치 | 4K 기준 바 x 1657~2178, 이름 글자 y 1980~1996. 고정이라 `BOSS_RECT=(1500,1850,850,250)` 기본 영역으로 충분 |
| 띠 패널 | 아이콘이 1개 이상일 때만 바 위에 어두운 패널이 그려지고 바 위 테두리가 text_y−14. **빈 띠는 패널이 없어 구형 보스(제바흐, 테두리 text_y−18)와 픽셀이 같다** → 보스 이름 해시로 "띠 보스"를 기억(bosses.json) |
| 띠 칸 | 프레임 첫 행 text_y−45, 14×14(1px 체크무늬 테두리, 내부 12×12), **피치 18, 시작 x = text_x−5 고정**, 왼쪽부터 빈칸 없이. 테두리 없는 아이콘도 있음(파란 X 검) → 테두리 어둡거나 내부가 확실한 그림이면 칸 |
| 라벨 | text_y−26, 7행. 상태창과 같은 5×7 숫자 + `M`(7×7). `4M`=4분, `40`=40초, 없음=시간 없음 |
| 아이콘 매칭 | 12×12 정규화 상관 ≥0.95 (다른 아이콘끼리 최대 0.915). **만료 직전 어둡게(~25%)/밝게(~145%, 255 클립) 깜빡임** → 템플릿 k배+clip 변형까지 비교. `stack` 태그 아이콘(숫자만 바뀜)은 ≥0.85 |
| 같은 아이콘 여러 개 | 표식 ×3 등. 추적기는 가장 긴 시간 하나로 |
| 잘린 아이콘 | 띠 시작 x가 어긋나면 잘린 그림이 "새 아이콘"으로 보임 → 스캔하지 않고 ±2px만 허용. **자동 등록은 기본 끔** |

## 5. 핵심 결정과 이유

- **행 검출은 캘리브레이션 때 1회, 실행 중엔 저장 좌표에서 읽기만.** 검출이 배경에 가장 취약한 단계라서.
- **활성 판정은 저장된 획 자리 픽셀 색.** 런타임 세그멘테이션 없음 → 배경 무관. 애매하면 "모름".
- **캘리브레이션은 어두운 곳에서.** 밝은 배경에선 209 회색 글자를 못 잘라 획 자리가 안 잡힘 (홈에 경고).
- **시간은 매 프레임 실측, 못 읽으면 추정(벽시계).** 늘어난 값은 2프레임 연속일 때만 재동기화.
- **캐릭터 = 프로필(명시적 선택).** 레이아웃이 화면과 안 맞으면(획 자리 판정 <60%) 감시 안 하고 "재설정하세요".
- **마스터 스위치 하나.** 켜면 전부, 끄면 트레이만. 게임이 뒤로 가면 인식도 쉼.
- **단축키는 폴링, 기본 꺼짐.** RegisterHotKey 는 게임에서 안 오고 키를 가로채서 제외.
- **오버레이 창은 캡처 제외**(WDA_EXCLUDEFROMCAPTURE). 옵션으로만 해제. OBS 는 디스플레이 캡처로.
- **미러는 항목별 독립 창.** 개별 드래그/휠 기본, Shift 로 그룹.
- **보스 디버프 감시는 띠 보스에서만.** 띠 패널이 한 번 보인 보스를 이름 해시로 기록 → 다음부터 바가 뜨는 즉시(빈 띠) 감시. 처음 보는 보스는 첫 디버프부터, 구형 레이드는 영원히 제외.
- **보스 디버프 빠짐 판정은 비대칭 디바운스.** 걸림 2프레임, 빠짐 4프레임, 남은 시간 30초 넘게 있던 것은 15프레임(이펙트가 띠를 덮는 경우). 바가 안 보이면 목록 숨김, 30초 넘게 안 보이면 전투 종료로 초기화.
- **아이콘 라이브러리는 고정(25개), 자동 등록 안 함.** 배경 탓에 변형된 그림이 쌓여서. 모르는 아이콘은 프레임만 저장하고 패치로 추가. 같은 이름 = 한 감시 항목(icon_ids).
- **버스트만 켜기 가능.** 감시(빠짐 목록) 없이 걸리는 순간 알림만 (붕파 같은 10초짜리).
- **이름은 표시용 상수만.** 저장소·모듈은 skilltrack, 사용자가 보는 이름·exe·로그는 core/paths.py 의 APP_NAME/EXE_NAME. exe(frozen)에선 assets 는 번들 안, profiles/diag/log 는 exe 옆 (BUILD.md).

## 6. 진단 방법

- `python win/watch.py --debug [--boss|--bossonly] [--learn]` : 콘솔 상태표 + 검출 박스 창. `s` 상태창 프레임 저장, `b` 보스 영역 저장(무손실)
- 자동 저장(일반 설정 "진단 저장"): `tests/fixtures/auto/` (상태창), `tests/fixtures/boss/auto/` (보스: newicon / nostrip / dropped / manual)
- 원칙: **원본 픽셀 없이 규칙을 고치지 않는다.** 이상한 프레임 → 픽스처 → 정답 박아 테스트 → 수정 → 기존 픽스처 전부 통과 확인
- 보스 픽스처 정답은 `tests/fixtures/boss/truth.json` ({파일: {labels, icons}}). 규칙을 바꿔 칸 수가 달라지면 이미지와 대조해 갱신
- "watch 는 되는데 run 은 안 됨" 류의 비교 정보가 원인 찾기에 가장 빠름

## 7. 다음 할 일 (ROADMAP.md 참조)

1. 배포: `pyinstaller skilltrack.spec` → dist/mabiaura zip. 아이콘(assets/icon.ico) 만들기. 가이드는 노션
2. 획 자리 자동 보강: 밝은 곳에서 캘리브레이션돼 빠진 행을 어두운 곳을 지날 때 채움
3. 체력/마나 (최후순위)

## 8. 새 대화 시작 문구

> skilltrack 프로젝트 이어서. HANDOFF.md 와 ROADMAP.md 첨부. 현재 코드는 git 최신. 다음: [할 일 번호]. 관련 파일은 요청하면 붙여넣겠음.
