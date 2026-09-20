"""
라이브 상태 감시 (콘솔). 오버레이 없음. 로직은 win/session.py.

사용법: python win/watch.py [행번호 ...] [--recalib] [--debug]
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))
from win.session import Session, event_text
from win.window import find_window, client_rect
from win.capture import Capture

STATUS_RECT = (2880, 1230, 300, 550)     # 클라이언트 기준. 패널 폭에 맞출 것
FPS = 5
KEEP_ROWS: set[int] = set()              # 임시: 유지 필수로 둘 행 번호


class Console:
    def __init__(self):
        self.events, self.last_draw = [], 0

    def log(self, msg):
        self.events.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        self.events = self.events[-15:]; self.last_draw = 0

    def draw(self, lines):
        if time.time() - self.last_draw < 1.0:
            return
        self.last_draw = time.time()
        os.system("cls" if os.name == "nt" else "clear")
        print("행  상태    흰/회   시간       (Ctrl+C 종료)")
        print(*lines, sep="\n"); print("-" * 44); print(*self.events, sep="\n")


def main(pick, recalib, debug):
    hwnd = find_window("마비노기")
    cx, cy, _, _ = client_rect(hwnd)
    sx, sy, sw, sh = STATUS_RECT
    cap = Capture()
    sess = Session(cap, (cx + sx, cy + sy, sw, sh), STATUS_RECT, pid="_console", recalib=recalib, pick=pick,
                   watch_opts=None)
    con = Console()
    for n in sess.notes:
        con.log(n)
    con.log(f"감시 {len(sess.tracker.tracks)}개 시작")

    while True:
        t0 = time.time()
        frame = cap.grab(sess.region)
        if frame is not None:
            r = sess.process(frame)
            for n in r.notes:
                con.log(n)
            for ev in r.events:
                con.log(f"{ev.label} {event_text(ev)}")

            lines = []
            for s in r.states:
                rd = r.readings.get(s.index)
                st = {"on": "활성  ", "off": "비활성", "unknown": "모름? "}[rd.state] if rd else "  -   "
                wg = f"{rd.white:.2f}/{rd.gray:.2f}" if rd else "  -  "
                tm = r.times.get(s.index, "")
                if (sec := r.secs.get(s.index)) is not None:
                    tm += f"  ={sec}s"
                elif r.ests.get(s.index) is not None:
                    tm += f"  ~{r.ests[s.index]}s (추정)"
                ext = ""
                if s.index in sess.sites and s.name_width and rd and rd.state == "on":
                    base = sess.sites[s.index].mask.shape[1]
                    ext = f"  연장(+{s.name_width - base}px)" if s.name_width >= base + 10 else ""
                lines.append(f"{s.index:2d}  {st}  {wg}  {tm}{ext}")
            con.draw(lines)

            if debug:
                vis = frame.copy()
                for s in r.states:
                    x, y, w, h = sess.layout.rows[s.index].text
                    rd = r.readings.get(s.index)
                    col = {"on": (0, 255, 0), "off": (128, 128, 128), "unknown": (0, 200, 255)}.get(rd.state if rd else "", (255, 255, 255))
                    cv2.rectangle(vis, (x - 1, y - 1), (x + w, y + h), col, 1)
                    if s.index in sess.sites:
                        site = sess.sites[s.index]; ys, xs = site.mask.nonzero()
                        vis[site.y + ys, site.x + xs] = col
                    if s.index in r.times:
                        cv2.putText(vis, r.times[s.index], (x + w + 4, y + h - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
                cv2.imshow("skilltrack debug (s: save frame, q: close)", cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    debug = False; cv2.destroyAllWindows()
                elif key == ord("s"):
                    con.log(f"프레임 저장 {sess.saver.save(frame, 'manual', force=True)}")
        time.sleep(max(0, 1 / FPS - (time.time() - t0)))


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        main([int(a) for a in args if a.isdigit()], "--recalib" in args, "--debug" in args)
    except KeyboardInterrupt:
        print("\n종료")