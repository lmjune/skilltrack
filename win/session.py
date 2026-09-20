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
from core import layout_store, variants

from core.paths import ASSETS, DIAG, UNKNOWN_DIR
ROOT = DIAG                        # 호환용
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
    """모르는 시간 글자 수집 (글자 라이브러리 보강용). 진단 저장이 켜져 있을 때만, 최대 max_files 장."""

    def __init__(self, folder: Path, enabled=True, max_files=30):
        self.folder, self.enabled, self.max_files = folder, enabled, max_files
        self.seen, self.last_warn = set(), {}

    def add(self, row_index, time_img, read, warn_every=5.0):
        new = 0
        for g in read.unknown:
            key = hashlib.md5(g.mask.tobytes() + bytes(g.mask.shape)).hexdigest()[:10]
            if key in self.seen:
                continue
            self.seen.add(key); new += 1
            if self.enabled and len(self.seen) <= self.max_files:
                self.folder.mkdir(parents=True, exist_ok=True)
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
    def __init__(self, cap, region, rect, pid, watch_opts=None, recalib=False, pick=None,
                 saver: FrameSaver | None = None, debounce=3, fps=5):
        """
        region: 화면 절대 좌표 캡처 영역. rect: 클라이언트 기준. pid: 프로필 id (레이아웃 파일 키).
        watch_opts: {row: Watch 필드}. None 이면 전 행을 기본값으로 감시(콘솔 개발용).
        """
        self.cap, self.region, self.rect, self.pid = cap, region, rect, pid
        self.lib = GlyphLib.load(ASSETS / "glyphs.json")
        self.saver = saver or FrameSaver(DIAG / "auto")
        self.unknown = UnknownGlyphs(UNKNOWN_DIR, enabled=self.saver.enabled)
        self.notes = []
        self.verify_ratio = None

        r = self._load_or_calibrate(recalib)
        if r is None:
            raise RuntimeError("상태창을 못 찾음. 상태창이 잘 보이는 곳(어두운 배경)에서 다시 시도하거나 영역을 확인하세요")
        self.layout, self.fps_, self.sites = r

        rows = pick or list(range(len(self.layout.rows)))
        watches = []
        for i in rows:
            if i not in self.fps_ or (watch_opts is not None and i not in watch_opts):
                continue
            opts = dict(alert_under=[60, 30], alert_under_extended=[120, 60], keep=False, keep_delay=10, keep_interval=30)
            opts.update((watch_opts or {}).get(i, {}))
            watches.append(Watch(self.fps_[i], opts.pop("label", f"행{i}"), row_index=i,
                                 base_width=self.sites[i].mask.shape[1] if i in self.sites else None, **opts))
        self.tracker = Tracker(watches, debounce=debounce)
        self.prev_time, self.unk_n = {}, {}
        self._variants = None
        self.last_read = {}          # row → 마지막으로 시간을 읽은 시각

    # ------------------------------------------------------------ 준비
    def _load_or_calibrate(self, recalib):
        saved = layout_store.load(self.pid)
        if saved and tuple(saved[0]) != tuple(self.rect):
            saved = None                                   # 영역이 바뀜 → 다시 검출
        if saved and not recalib:
            _, L, fps, sites = saved
            ratio = layout_store.verify(self.cap.grab_sure(self.region), sites)
            self.verify_ratio = ratio
            if ratio >= VERIFY_MIN:
                self.notes.append(f"저장된 레이아웃 사용 (획 자리 판정 {ratio:.0%})")
            else:
                # 다른 캐릭터로 접속했거나 고정 목록이 바뀐 것. 저장본을 멋대로 덮어쓰지 않는다 (명시적 '레이아웃 다시'만)
                self.notes.append(f"⚠ 저장된 레이아웃과 화면이 안 맞음 ({ratio:.0%}). 다른 캐릭터면 홈에서 전환, 고정 목록을 바꿨으면 '레이아웃 다시'")
            return L, fps, sites
        r = calibrate(self.cap, self.region)
        if r is None:
            if saved:
                self.notes.append("⚠ 재검출 실패 → 저장본 그대로 사용")
                return saved[1], saved[2], saved[3]
            return None
        layout, frame = r
        if saved and len(layout.sections[0]) < len(saved[1].rows) and not recalib:
            self.notes.append(f"⚠ 새 검출 {len(layout.sections[0])}행 < 저장본 {len(saved[1].rows)}행 → 저장본 유지")
            return saved[1], saved[2], saved[3]
        pinned = sorted(layout.sections[0])
        layout.rows = [layout.rows[i] for i in pinned]
        layout.sections = [list(range(len(layout.rows)))]
        layout.widen(frame.shape[1])
        states = parse_rows(frame, layout)
        layout_store.save(self.pid, layout, states, self.rect, frame)
        _, L, fps, sites = layout_store.load(self.pid)
        missing = [i for i in range(len(L.rows)) if i not in sites]
        if missing:
            # 밝은 배경에선 비활성(회색) 글자를 못 잘라 그 행의 획 자리가 안 잡힌다 → 그 행은 판정 불가
            self.notes.append(f"⚠ 행 {missing} 의 획 자리를 못 잡음 (밝은 곳에서 검출됨). 어두운 곳에서 '레이아웃 다시'를 권장")
        self.notes.append(f"검출 완료: {len(L.rows)}행 저장")
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
            else:
                # 획 자리가 없는 행: 파싱으로 대신. 255 획이 있으면 활성, 없으면 모름 (밝은 배경에선 비활성 확정 불가)
                s.active = True if (s.name_range and s.active) else None

        for i, rd in readings.items():
            self.unk_n[i] = self.unk_n.get(i, 0) + 1 if rd.state == "unknown" else 0
            if self.unk_n[i] == 10 and (n := self.saver.save(frame, f"unknownstate_row{i}")):
                notes.append(f"행{i} 판정 불가 지속 → 프레임 저장 {n}")

        secs, times = {}, {}
        now = time.time()
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
            if rr.seconds is not None:
                self.last_read[s.index] = now
            if rr.seconds is not None and self.layout.time_right is None:
                self.layout.time_right = self.layout.rows[s.index].text[0] + s.time_range[1]
                layout_store.update_time_right(self.pid, self.layout.time_right)
                notes.append(f"시간 끝 열 학습: {self.layout.time_right}")
            if rr.unknown:
                if (m := self.unknown.add(s.index, s.time_img, rr)):
                    notes.append(m)
                if (n := self.saver.save(frame, f"unknown_row{s.index}")):
                    notes.append(f"  프레임 저장 {n}")

        # 접미어 변형: 이름이 기준 폭보다 길면 그 뒤 획을 잘라 알려진 접미어와 비교
        for s in states:
            site = self.sites.get(s.index)
            if site is None or s.name_range is None or s.active is not True:
                continue
            base_w = site.mask.shape[1]
            if s.name_width < base_w + 10:
                s.extended = False; continue
            from core.strokes import stroke_masks
            w_, g_, _ = stroke_masks(s.name_img)
            suffix = (w_ | g_)[:, base_w:]
            if suffix.sum() < 10:
                s.extended = False; continue
            if self._variants is None:
                self._variants = variants.load(self.pid, None)
            ext, key, new = variants.classify(self.pid, s.index, suffix, s.name_img[:, base_w:], self._variants)
            if new:
                self._variants = variants.load(self.pid, None)
                notes.append(f"행{s.index}: 새 이름 접미어 저장 ({key}). 감시 항목에서 '연장으로 취급' 여부를 정하세요")
            s.extended = ext

        # 진단: 활성 행인데 10초 넘게 시간을 못 읽으면 프레임 저장 (왜 못 읽는지 볼 수 있게)
        for s in states:
            if s.active is True and s.index in self.last_read and now - self.last_read[s.index] > 10 and secs.get(s.index) is None:
                if (n := self.saver.save(frame, f"timelost_row{s.index}")):
                    notes.append(f"행{s.index} 시간 {now - self.last_read[s.index]:.0f}초째 못 읽음 → 프레임 저장 {n}")
                    self.last_read[s.index] = now      # 10초마다 한 번만

        events = self.tracker.update(states, secs)
        for ev in events:
            if ev.kind == "lost" and (n := self.saver.save(frame, f"lost_row{ev.label[1:]}")):
                notes.append(f"  프레임 저장 {n}")
        return Result(states, readings, secs, times, self.tracker.estimates(), events, notes)


def event_text(ev: Event) -> str:
    v = ev.value
    if ev.kind == "under":
        return f"{v}초 미만"
    if ev.kind == "resync":
        return f"갱신됨 → {v // 60}분 {v % 60}초" if v is not None else "갱신됨"
    return {"off": "꺼짐", "on": "켜짐", "lost": "목록에서 사라짐", "found": "다시 보임",
            "extended": "연장됨", "unextended": "연장 끝", "keep": "꺼진 상태 유지 중 (켜세요)"}.get(ev.kind, ev.kind)