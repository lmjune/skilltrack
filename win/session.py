"""
상태창 감시 세션: 레이아웃 준비 + 프레임 처리. 화면 출력·소리는 모른다.

    s = Session(cap, region, recalib=False)   # 저장 레이아웃 검증 → 실패 시 검출
    r = s.process(frame)                     # → Result (상태, 판정, 시간, 이벤트, 추정)

콘솔(watch.py)과 오버레이(run.py)가 같은 세션을 쓴다.
"""
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2

from core.rows import detect_rows
from core.status import parse_rows
from core.digits import GlyphLib, read_time
from core.tracker import Tracker, Watch, Event
from core.pixelwatch import read_site, Reading
from core import layout_store

ROOT = Path(__file__).parent.parent
LAYOUT_FILE = ROOT / "profiles" / "status_layout.json"
CALIB_FRAMES = 10
VERIFY_MIN = 0.6


@dataclass
class Result:
    states: list
    readings: dict            # row → Reading
    secs: dict                # row → 읽은 초 (None 이면 못 읽음)
    times: dict               # row → 시간 텍스트
    ests: dict                # row → 추정 초
    events: list[Event]
    notes: list[str] = field(default_factory=list)   # 로그용 (학습, 저장 등)


class FrameSaver:
    """의심 프레임 저장. 종류(reasons)를 좁혀 놓으면 그것만 저장."""

    def __init__(self, folder: Path, reasons=("unknown", "unknownstate", "timelost", "lost"),
                 min_gap=10.0, max_files=30, enabled=True):
        self.folder, self.reasons = folder, reasons
        self.min_gap, self.max_files, self.enabled = min_gap, max_files, enabled
        self.last, self.count = 0.0, 0
        if enabled:
            folder.mkdir(parents=True, exist_ok=True)

    def save(self, frame, reason, force=False):
        if not self.enabled or (not force and reason.split("_")[0] not in self.reasons):
            return None
        now = time.time()
        if not force and (now - self.last < self.min_gap or self.count >= self.max_files):
            return None
        self.last = now; self.count += 1
        name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{reason}.png"
        ok, buf = cv2.imencode(".png", frame)
        if ok:
            (self.folder / name).write_bytes(buf.tobytes())
        return name


class UnknownGlyphs:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.seen, self.last_warn = set(), {}

    def add(self, row_index, time_img, read, warn_every=5.0):
        """새 글자면 저장. 경고할 때만 문자열 반환."""
        new = 0
        for g in read.unknown:
            key = hashlib.md5(g.mask.tobytes() + bytes(g.mask.shape)).hexdigest()[:10]
            if key in self.seen:
                continue
            self.seen.add(key); new += 1
            cv2.imwrite(str(self.folder / f"{key}.png"), time_img[:, g.x0:g.x1])
            cv2.imwrite(str(self.folder / f"{key}_time.png"), time_img)
        now = time.time()
        if new or now - self.last_warn.get(row_index, 0) > warn_every:
            self.last_warn[row_index] = now
            return f"⚠ 모르는 글자 (행{row_index}: {read.text}){' → 저장' if new else ''}"
        return None


def calibrate(cap, region):
    best = None
    for _ in range(CALIB_FRAMES):
        frame = cap.grab_sure(region)
        L = detect_rows(frame)
        if L is not None and L.sections:
            n = len(L.sections[0])
            if best is None or n > best[0]:
                best = (n, L, frame)
        time.sleep(0.2)
    return None if best is None else (best[1], best[2])


class Session:
    def __init__(self, cap, region, rect, recalib=False, pick=None, watch_opts=None,
                 saver: FrameSaver | None = None, debounce=3, fps=5, keep_needs_activity=True):
        """
        region: 화면 절대 좌표 캡처 영역. rect: 클라이언트 기준 (저장 키).
        watch_opts: {row: dict(Watch 필드)} 행별 알림 설정. 없으면 기본.
        """
        self.cap, self.region, self.rect = cap, region, rect
        self.lib = GlyphLib.load(ROOT / "assets" / "glyphs.json")
        self.unknown = UnknownGlyphs(ROOT / "assets" / "unknown")
        self.saver = saver or FrameSaver(ROOT / "tests" / "fixtures" / "auto")
        self.notes = []

        r = self._load_or_calibrate(recalib)
        if r is None:
            raise RuntimeError("상태창을 못 찾음. 상태창이 잘 보이는 상태에서 다시 실행하거나 캡처 영역 확인")
        self.layout, self.fps_, self.sites = r

        rows = pick or list(range(len(self.layout.rows)))
        watches = []
        for i in rows:
            if i not in self.fps_:
                continue
            opts = dict(alert_under=[60, 30], alert_under_extended=[120, 60],
                        keep=False, keep_delay=10, keep_interval=30)
            opts.update((watch_opts or {}).get(i, {}))
            watches.append(Watch(self.fps_[i], opts.pop("label", f"행{i}"), row_index=i,
                                 base_width=self.sites[i].mask.shape[1] if i in self.sites else None, **opts))
        self.tracker = Tracker(watches, debounce=debounce, keep_needs_activity=keep_needs_activity)
        self.prev_time, self.unk_n = {}, {}

    # ------------------------------------------------------------ 준비
    def _load_or_calibrate(self, recalib):
        saved = layout_store.load(LAYOUT_FILE)
        if saved and (tuple(saved[0]) != tuple(self.rect) or not saved[3]):
            saved = None
        if saved and not recalib:
            _, L, fps, sites = saved
            frame = self.cap.grab_sure(self.region)
            # 검증은 획 자리로 (배경 무관). 이름 지문은 밝은 배경에서 비활성 글자를 못 잘라 못 믿는다
            reads = [read_site(frame, site) for site in sites.values()]
            ratio = sum(1 for r in reads if r.state != "unknown") / max(1, len(reads))
            if ratio >= VERIFY_MIN:
                self.notes.append(f"저장된 레이아웃 사용 (획 자리 판정 {ratio:.0%})")
                return L, fps, sites
            self.notes.append(f"저장된 레이아웃 획 자리 판정 {ratio:.0%} → 재검출 시도")
        r = calibrate(self.cap, self.region)
        if r is None:
            if saved:
                self.notes.append("⚠ 재검출 실패 → 저장본 그대로 사용 (상태창이 가려졌거나 배경이 밝음)")
                return saved[1], saved[2], saved[3]
            return None
        layout, frame = r
        prev = layout_store.load(LAYOUT_FILE)
        if prev and len(layout.sections[0]) < len(prev[1].rows):
            # 밝은 곳이거나 뭔가 가린 상태에서 검출하면 행이 덜 잡힌다. 더 나은 저장본을 덮어쓰지 않는다
            self.notes.append(f"⚠ 새 검출 {len(layout.sections[0])}행 < 저장본 {len(prev[1].rows)}행 → 저장본 유지. "
                              f"어두운 곳에서 상태창이 다 보일 때 --recalib 하세요")
            return prev[1], prev[2], prev[3]
        pinned = sorted(layout.sections[0])
        layout.rows = [layout.rows[i] for i in pinned]
        layout.sections = [list(range(len(layout.rows)))]
        layout.widen(frame.shape[1])
        states = parse_rows(frame, layout)
        layout_store.save(LAYOUT_FILE, layout, states, self.rect, frame=frame)
        _, L, fps, sites = layout_store.load(LAYOUT_FILE)
        self.notes.append(f"검출 완료, {len(L.rows)}행 + 획 자리 저장 → {LAYOUT_FILE.name}")
        return L, fps, sites

    # ------------------------------------------------------------ 처리
    def process(self, frame) -> Result:
        notes = []
        states = parse_rows(frame, self.layout)
        readings = {}
        for s in states:
            if s.index in self.sites:
                rd = read_site(frame, self.sites[s.index])
                readings[s.index] = rd
                s.active = {"on": True, "off": False}.get(rd.state)

        for i, rd in readings.items():
            self.unk_n[i] = self.unk_n.get(i, 0) + 1 if rd.state == "unknown" else 0
            if self.unk_n[i] == 10 and (n := self.saver.save(frame, f"unknownstate_row{i}")):
                notes.append(f"행{i} 판정 불가 지속 → 프레임 저장 {n}")

        secs, times = {}, {}
        for s in states:
            had, now_has = self.prev_time.get(s.index, False), s.time_img is not None
            if had and not now_has and s.active and (n := self.saver.save(frame, f"timelost_row{s.index}")):
                notes.append(f"행{s.index} 시간 사라짐 → 프레임 저장 {n}")
            self.prev_time[s.index] = now_has
            if s.time_img is None:
                continue
            rr = read_time(s.time_img, self.lib)
            if not rr.plausible:
                continue
            secs[s.index], times[s.index] = rr.seconds, rr.text
            if rr.seconds is not None and self.layout.time_right is None:
                self.layout.time_right = self.layout.rows[s.index].text[0] + s.time_range[1]
                layout_store.update_time_right(LAYOUT_FILE, self.layout.time_right)
                notes.append(f"시간 끝 열 학습: {self.layout.time_right}")
            if rr.unknown:
                if (m := self.unknown.add(s.index, s.time_img, rr)):
                    notes.append(m)
                if (n := self.saver.save(frame, f"unknown_row{s.index}")):
                    notes.append(f"  프레임 저장 {n}")

        events = self.tracker.update(states, secs)
        for ev in events:
            if ev.kind == "lost" and (n := self.saver.save(frame, f"lost_row{ev.label[1:]}")):
                notes.append(f"  프레임 저장 {n}")
        return Result(states, readings, secs, times, self.tracker.estimates(), events, notes)


def event_text(ev: Event) -> str:
    return {"off": "꺼짐", "on": "켜짐", "lost": "목록에서 사라짐", "found": "다시 보임",
            "under": f"{ev.value}초 미만", "extended": "연장됨", "unextended": "연장 끝",
            "resync": f"시간 재동기화 → {ev.value}초", "keep": "꺼진 상태 유지 중 (켜세요)"}[ev.kind]