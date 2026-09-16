"""
라이브 상태 감시 (콘솔 버전). 오버레이 없음.

시작:
  1) profiles/status_layout.json 이 있으면 저장된 좌표에서 지문 검증 → 통과하면 바로 시작
  2) 없거나 실패하면 몇 프레임 동안 행 검출 → 가장 많은 행이 잡힌 결과를 채택 → 획 자리까지 저장
실행 중:
  활성/비활성 = 저장된 획 자리의 픽셀 색만 읽음 (배경 무관, 애매하면 '모름')
  시간        = 오른쪽 정렬 영역에서 글자 매칭
  1초마다 행 상태표 갱신, 이벤트는 그 아래 누적 출력

사용법: python win/watch.py [행번호 ...] [--recalib] [--debug]
  --recalib : 저장된 레이아웃 무시하고 다시 검출
  --debug   : 캡처 영역에 판정을 그린 창 표시 (s: 원본 프레임 저장, q: 닫기)
"""
import hashlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.rows import detect_rows
from core.status import parse_rows, fp_same
from core.digits import GlyphLib, read_time
from core.tracker import Tracker, Watch
from core.pixelwatch import read_site
from core import layout_store
from win.window import find_window, client_rect
from win.capture import Capture

ROOT = Path(__file__).parent.parent
LAYOUT_FILE = ROOT / "profiles" / "status_layout.json"
STATUS_RECT = (2880, 1230, 300, 550)     # 패널 폭에 맞출 것 (넓으면 패널 밖 밝은 배경이 글자로 오인됨)
FPS = 5
CALIB_FRAMES = 10
VERIFY_MIN = 0.6
WARN_EVERY = 5.0


class UnknownGlyphs:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.seen, self.last_warn = set(), {}

    def add(self, row_index, time_img, read, log):
        new = 0
        for g in read.unknown:
            key = hashlib.md5(g.mask.tobytes() + bytes(g.mask.shape)).hexdigest()[:10]
            if key in self.seen:
                continue
            self.seen.add(key); new += 1
            cv2.imwrite(str(self.folder / f"{key}.png"), time_img[:, g.x0:g.x1])
            cv2.imwrite(str(self.folder / f"{key}_time.png"), time_img)
            cv2.imwrite(str(self.folder / f"{key}_x8.png"),
                        cv2.resize(time_img, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST))
        now = time.time()
        if new or now - self.last_warn.get(row_index, 0) > WARN_EVERY:
            self.last_warn[row_index] = now
            log(f"⚠ 모르는 글자 (행{row_index}: {read.text}){' → 저장' if new else ''}")


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


def load_or_calibrate(cap, region, recalib):
    if not recalib:
        saved = layout_store.load(LAYOUT_FILE)
        if saved and tuple(saved[0]) == STATUS_RECT and saved[3]:
            _, L, fps, sites = saved
            ratio = layout_store.verify(cap.grab_sure(region), L, fps)
            print(f"저장된 레이아웃 지문 일치율 {ratio:.0%}", end=" → ")
            if ratio >= VERIFY_MIN:
                print("사용"); return L, fps, sites
            print("재검출")
    print(f"상태창 검출 중 ({CALIB_FRAMES}프레임)...")
    r = calibrate(cap, region)
    if r is None:
        return None
    layout, frame = r
    pinned = sorted(layout.sections[0])
    layout.rows = [layout.rows[i] for i in pinned]
    layout.sections = [list(range(len(layout.rows)))]
    layout.widen(frame.shape[1])              # 시간은 캘리브레이션 때 안 보일 수 있으니 끝까지 탐색
    states = parse_rows(frame, layout)
    layout_store.save(LAYOUT_FILE, layout, states, STATUS_RECT, frame=frame)
    _, L, fps, sites = layout_store.load(LAYOUT_FILE)
    print(f"검출 완료, {len(L.rows)}행 + 획 자리 저장 → {LAYOUT_FILE.name}")
    return L, fps, sites


class FrameSaver:
    """의심스러운 순간의 원본 프레임 저장. 나중에 픽스처로 쓴다."""

    def __init__(self, folder: Path, min_gap=10.0, max_files=30):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.min_gap, self.max_files = min_gap, max_files
        self.last, self.count = 0.0, 0

    def save(self, frame, reason, force=False):
        now = time.time()
        if not force and (now - self.last < self.min_gap or self.count >= self.max_files):
            return None
        self.last = now; self.count += 1
        name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{reason}.png"
        ok, buf = cv2.imencode(".png", frame)          # cv2.imwrite 는 윈도우에서 비ASCII 경로에 조용히 실패
        if ok:
            (self.folder / name).write_bytes(buf.tobytes())
        return name


class Console:
    """상태표는 제자리 갱신, 이벤트는 아래에 누적."""

    def __init__(self, n_rows):
        self.n = n_rows
        self.events = []
        self.last_draw = 0

    def log(self, msg):
        self.events.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        self.events = self.events[-15:]
        self.last_draw = 0

    def draw(self, lines, force=False):
        if not force and time.time() - self.last_draw < 1.0:
            return
        self.last_draw = time.time()
        os.system("cls" if os.name == "nt" else "clear")
        print("행  상태    흰/회   시간       (Ctrl+C 종료)")
        for ln in lines:
            print(ln)
        print("-" * 44)
        for e in self.events:
            print(e)


def main(pick, recalib, debug):
    hwnd = find_window("마비노기")
    cx, cy, cw, ch = client_rect(hwnd)
    cap = Capture()
    lib = GlyphLib.load(ROOT / "assets" / "glyphs.json")
    unknown = UnknownGlyphs(ROOT / "assets" / "unknown")
    sx, sy, sw, sh = STATUS_RECT
    region = (cx + sx, cy + sy, sw, sh)

    r = load_or_calibrate(cap, region, recalib)
    if r is None:
        print("상태창을 못 찾음. 상태창이 잘 보이는 상태에서 다시 실행하거나 STATUS_RECT 확인"); return
    layout, fps, sites = r

    targets = pick or list(range(len(layout.rows)))
    # 임시 설정: 모든 행 기본 60/30초, 연장되면 120/60초. (설정 UI 생기면 항목별로)
    # 임시 설정 (설정 UI 생기면 항목별로): 모든 행 기본 60/30초, 연장 시 120/60초, 유지 필수는 꺼둠.
    # 유지 필수를 시험하려면 예: KEEP_ROWS = {1, 5} 처럼 행 번호를 넣으면 됨
    KEEP_ROWS: set[int] = set()
    tracker = Tracker([Watch(fps[i], f"행{i}", alert_under=[60, 30],
                             base_width=sites[i].mask.shape[1] if i in sites else None,
                             alert_under_extended=[120, 60], row_index=i,
                             keep=(i in KEEP_ROWS), keep_delay=10, keep_interval=30)
                       for i in targets if i in fps], debounce=3)
    con = Console(len(layout.rows))
    saver = FrameSaver(ROOT / "tests" / "fixtures" / "auto")
    con.log(f"감시 {len(tracker.tracks)}개 시작 (의심 프레임 자동 저장 → tests/fixtures/auto/)")
    prev_time = {}
    unk_n = {}

    while True:
        t0 = time.time()
        frame = cap.grab(region)
        if frame is not None:
            states = parse_rows(frame, layout)
            # 활성 판정은 획 자리 픽셀로 대체 (모름 = None)
            readings = {}
            for s in states:
                if s.index in sites:
                    rd = read_site(frame, sites[s.index])
                    readings[s.index] = rd
                    s.active = {"on": True, "off": False}.get(rd.state)

            # '모름'이 오래 이어지면 의심 (어떤 상황인지 프레임으로 확인)
            for i, rd in readings.items():
                unk_n[i] = unk_n.get(i, 0) + 1 if rd.state == "unknown" else 0
                if unk_n[i] == 10 and (n := saver.save(frame, f"unknownstate_row{i}")):
                    con.log(f"행{i} 판정 불가 지속 → 프레임 저장 {n}")

            secs, times = {}, {}
            # 활성 행에서 시간이 읽히다가 사라지면 의심 (배경 때문에 시간 글자를 놓친 순간)
            for s in states:
                had = prev_time.get(s.index, False)
                now_has = s.time_img is not None
                if had and not now_has and s.active and (n := saver.save(frame, f"timelost_row{s.index}")):
                    con.log(f"행{s.index} 시간 사라짐 → 프레임 저장 {n}")
                prev_time[s.index] = now_has
            for s in states:
                if s.time_img is None:
                    continue
                rr = read_time(s.time_img, lib)
                if not rr.plausible:          # 초/분으로 안 끝남 = 배경 잡음
                    continue
                secs[s.index] = rr.seconds
                times[s.index] = rr.text
                if rr.seconds is not None and layout.time_right is None:
                    # 처음으로 제대로 읽힌 시간 → 끝 열 학습·저장 (이후 오른쪽 정렬 검증에 사용)
                    x0 = layout.rows[s.index].text[0]
                    layout.time_right = x0 + s.time_range[1]
                    layout_store.update_time_right(LAYOUT_FILE, layout.time_right)
                    con.log(f"시간 끝 열 학습: {layout.time_right}")
                if rr.unknown:
                    unknown.add(s.index, s.time_img, rr, con.log)
                    if (n := saver.save(frame, f"unknown_row{s.index}")):
                        con.log(f"  프레임 저장 {n}")

            for ev in tracker.update(states, secs):
                msg = {"off": "꺼짐", "on": "켜짐", "lost": "목록에서 사라짐", "found": "다시 보임",
                       "under": f"{ev.value}초 미만", "extended": "연장됨 (이름 길어짐)",
                       "unextended": "연장 끝", "resync": f"시간 재동기화 → {ev.value}초",
                       "keep": "꺼진 상태 유지 중 (켜세요)"}[ev.kind]
                con.log(f"{ev.label} {msg}")
                if ev.kind in ("off", "lost") and (n := saver.save(frame, f"{ev.kind}_row{ev.label[1:]}")):
                    con.log(f"  프레임 저장 {n}")

            ests = tracker.estimates()
            lines = []
            for s in states:
                rd = readings.get(s.index)
                st = {"on": "활성  ", "off": "비활성", "unknown": "모름? "}[rd.state] if rd else "  -   "
                wg = f"{rd.white:.2f}/{rd.gray:.2f}" if rd else "  -  "
                tm = times.get(s.index, "")
                sec = secs.get(s.index)
                if sec is not None:
                    tm += f"  ={sec}s"
                elif ests.get(s.index) is not None:
                    tm += f"  ~{ests[s.index]}s (추정)"
                ext = ""
                if s.index in sites and s.name_width and rd and rd.state == "on":
                    base = sites[s.index].mask.shape[1]
                    ext = f"  연장(+{s.name_width - base}px)" if s.name_width >= base + 10 else ""
                lines.append(f"{s.index:2d}  {st}  {wg}  {tm}{ext}")
            con.draw(lines)

            if debug:
                vis = frame.copy()
                for s in states:
                    x, y, w, h = layout.rows[s.index].text
                    rd = readings.get(s.index)
                    col = {"on": (0, 255, 0), "off": (128, 128, 128), "unknown": (0, 200, 255)}.get(rd.state if rd else "", (255, 255, 255))
                    cv2.rectangle(vis, (x - 1, y - 1), (x + w, y + h), col, 1)
                    if s.index in sites:
                        site = sites[s.index]
                        ys, xs = site.mask.nonzero()
                        vis[site.y + ys, site.x + xs] = col
                    if s.time_img is not None:
                        cv2.putText(vis, times.get(s.index, "?"), (x + w + 4, y + h - 2),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
                cv2.imshow("skilltrack debug (s: save frame, q: close)",
                           cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
                key = cv2.waitKey(1) & 0xFF
                if key == ord("s"):
                    con.log(f"프레임 저장 {saver.save(frame, 'manual', force=True)}")
                elif key == ord("q"):
                    debug = False; cv2.destroyAllWindows()

        time.sleep(max(0, 1 / FPS - (time.time() - t0)))


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        main([int(a) for a in args if a.isdigit()], "--recalib" in args, "--debug" in args)
    except KeyboardInterrupt:
        print("\n종료")