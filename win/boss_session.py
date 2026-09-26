"""
보스 디버프 세션: 바 영역 프레임 → 읽기(core.bossbar) → 추적(core.bosstrack). 화면 출력·소리는 모른다.

    bs = BossSession(watches)                 # watches: [DebuffWatch]. 비우면 인식·수집만
    r = bs.process(frame_region)              # → BossResult

- 바 위치는 화면 고정이라 기본 영역(BOSS_RECT, 클라이언트 기준)으로 충분. 프로필 regions.boss 가 있으면 그걸 쓴다.
- 모르는 아이콘은 기본적으로 등록하지 않는다 (배경 탓에 변형된 그림이 쌓임). 프레임만 저장해 두고 필요하면 패치로 추가.
  일반 설정 boss_learn_icons(디버그)를 켜면 자동 등록.
- 빈 띠(아무것도 안 걸림)는 패널이 안 그려져 구형 보스 바와 구분이 안 된다 → 보스 이름(글자 마스크 해시)으로 기억한다.
  띠 패널이 한 번 보인 보스는 bosses.json 에 기록, 다음부터 바가 뜨는 순간 감시 시작. 처음 보는 보스는 첫 디버프부터.
- 진단 저장: 새 아이콘 등장 프레임, 바는 있는데 띠 위치를 못 잡는 프레임 → tests/fixtures/boss/auto/
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

import json

from core.bossbar import BarRead, IconLib, read_bar, find_bar_diag, name_key
from core.bosstrack import BossTracker, DebuffEvent, DebuffWatch
from core.digits import GlyphLib
from win.session import FrameSaver

from core.paths import ASSETS, DIAG
BOSS_RECT = (1500, 1850, 850, 250)      # 4K 기준. 바 1657~2178 × 1962~2011 + 띠 35행 위 를 여유 있게


def boss_rect(client_w, client_h):
    """바는 화면 가로 중앙·하단 고정 (4K 실측: 중심 x≈1918, 이름 y=2160−180). 다른 해상도는 같은 상대 위치로 가정 (미검증)."""
    from core import screen
    s = screen.scale()
    if (client_w, client_h) == (3840, 2160) and s == 1.0:
        return BOSS_RECT
    # UI 크기에 비례 (150% 실측: 이름 y = 2160 − 270, 가로 중앙 그대로)
    hw, top, w, h = int(425 * s), int(310 * s), int(850 * s), int(250 * s)
    x = max(0, client_w // 2 - hw)
    y = max(0, client_h - top)
    return (x, y, min(w, client_w - x), min(h, client_h - y))
ICON_DIR = ASSETS / "boss_icons"
BOSSES_FILE = ICON_DIR / "bosses.json"    # {이름 해시: {"strip": true, "pct_sample": "…"}} 띠 패널이 한 번이라도 보인 보스


@dataclass
class BossResult:
    read: BarRead
    events: list[DebuffEvent]
    shown: list                    # [DebuffState] 오버레이에 보여줄 것
    notes: list[str] = field(default_factory=list)


class BossSession:
    def __init__(self, watches: list[DebuffWatch] | None = None, saver: FrameSaver | None = None, learn=True, verbose=False):
        self.verbose = verbose                    # 바를 못 찾는 이유 진단 출력 (콘솔 감시용)
        from core import screen
        sc = screen.current()
        self.lib = GlyphLib.load(screen.boss_glyphs(), fuzzy=sc.fuzzy)    # 라벨 글자 (150% 는 부드러운 글꼴)
        self.icons = IconLib(ICON_DIR)
        self.tracker = BossTracker(watches or [])
        self.saver = saver or FrameSaver(DIAG / "boss" / "auto", reasons=("newicon", "nostrip", "nopanel", "dropped", "manual"))
        self.learn = learn
        self.was_present = False
        self.last_strip_n = 0
        self.bosses = json.loads(BOSSES_FILE.read_text(encoding="utf-8")) if BOSSES_FILE.exists() else {}
        self.boss_key = None
        self.last_diag = 0.0

    def set_watches(self, watches: list[DebuffWatch]):
        self.tracker = BossTracker(watches)

    def process(self, frame) -> BossResult:
        notes = []
        r = read_bar(frame, self.lib, self.icons)
        if r.present:
            key = name_key(frame, r.anchor)
            if r.strip and not self.bosses.get(key, {}).get("strip"):
                self.bosses[key] = {"strip": True}
                try:
                    BOSSES_FILE.parent.mkdir(parents=True, exist_ok=True)
                    BOSSES_FILE.write_text(json.dumps(self.bosses, indent=1), encoding="utf-8")
                    notes.append("띠 보스로 기록 (다음부터 바가 뜨면 바로 감시)")
                except OSError:
                    pass
            if not r.strip and self.bosses.get(key, {}).get("strip"):
                r.strip = True                      # 알려진 띠 보스인데 아직 아무것도 안 걸림 → 빈 띠
            self.boss_key = key
        if r.present != self.was_present:
            notes.append("보스 바 보임" if r.present else "보스 바 사라짐")
            self.was_present = r.present
            if r.present and not r.has_strip:
                notes.append("  띠 패널 없음 (처음 보는 보스면 첫 디버프부터, 구형 보스면 감시 안 함)")
        if self.verbose and not r.present and time.time() - self.last_diag > 5:
            # 왜 못 찾는지: '%' 최소 차이 + 영역 안 최대 밝기. 바가 보이는데 이게 계속 뜨면 프레임을 b 로 저장
            self.last_diag = time.time()
            _, diff, (x, y) = find_bar_diag(frame)
            mx = int(frame.min(axis=2).max())
            notes.append(f"  (바 못 찾음: '%' 최소 차이 {diff}px @({x},{y}), 영역 내 가장 흰 픽셀 min-채널 {mx})")

        # 모르는 아이콘: 기본은 등록하지 않고 프레임만 저장(진단). learn=True(일반 설정, 디버그용)면 라이브러리에 등록
        unknown = [s for s in r.slots if s.icon_id is None and not self.icons.is_dim(s.icon)]
        if unknown:
            if self.learn:
                for s in unknown:
                    s.icon_id = self.icons.add(s.icon)
                notes.append(f"새 디버프 아이콘 {len(unknown)}개 등록 (assets/boss_icons, 이름 없음)")
            if (n := self.saver.save(frame, "newicon")):
                notes.append(f"모르는 아이콘 {len(unknown)}개 → 프레임 저장 {n}")

        # 띠 패널은 있는데 칸 수가 갑자기 0 → 띠를 못 잡은 것일 수 있음 (진짜 다 빠진 것일 수도). 프레임 저장해 두고 나중에 확인
        if r.has_strip and not r.slots and self.last_strip_n > 0:
            if (n := self.saver.save(frame, "nostrip")):
                notes.append(f"띠 사라짐 → 프레임 저장 {n}")
        self.last_strip_n = len(r.slots)

        events = self.tracker.update(r)
        if r.present and any(st.suspect for st in self.tracker.states.values()):
            names = ", ".join(st.watch.label for st in self.tracker.states.values() if st.suspect)
            if (n := self.saver.save(frame, "dropped")):
                notes.append(f"{names}: 시간 남았는데 안 보임 → 프레임 저장 {n}")
        shown = self.tracker.shown() if r.present else []     # 바가 안 보이면(메뉴·전투 종료) 목록도 숨김. 상태는 30초까지 유지
        return BossResult(r, events, shown, notes)

    def save_frame(self, frame) -> str | None:
        return self.saver.save(frame, "manual", force=True)


def debuff_event_text(ev: DebuffEvent) -> str:
    if ev.kind == "under":
        return f"{ev.value}초 이하"
    if ev.kind == "burst":
        return ev.label            # 라벨에 이미 "… 적용!" 문구
    return {"missing": "빠짐", "found": "걸림", "burst_off": "버스트 끝", "start": "보스 디버프 감시 시작", "end": "전투 종료"}.get(ev.kind, ev.kind)


def watches_from_names(icons: IconLib, names: list[str], thresholds=(60, 40, 20), burst: dict | None = None) -> list[DebuffWatch]:
    """이름(icons.json 의 name)으로 감시 목록 생성. burst: {name: 문구}. 콘솔/임시용."""
    burst = burst or {}
    out = []
    for k, m in icons.meta.items():
        if m.get("name") in names:
            out.append(DebuffWatch(k, m["name"], list(thresholds), burst=m["name"] in burst, burst_text=burst.get(m["name"], "")))
    return out