"""
라이브 상태 감시 (콘솔). 오버레이 없음. 로직은 win/session.py.

사용법: python win/watch.py [행번호 ...] [--recalib] [--debug] [--boss] [--bossonly]
  --boss      상태창 + 보스 디버프 띠 같이 감시 (전체 화면 1회 캡처 후 잘라 씀)
  --bossonly  보스 띠만 (상태창 세션 안 만듦)
  --learn     모르는 디버프 아이콘을 assets/boss_icons 에 등록 (기본은 프레임 저장만)
  --debug 창에서 s: 상태창 프레임 저장, b: 보스 바 영역 저장 (무손실, tests/fixtures/boss/auto), q: 창 닫기
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))
from win.session import Session, event_text
from win.boss_session import BossSession, BOSS_RECT, debuff_event_text
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

    def draw(self, lines, boss_lines=None):
        if time.time() - self.last_draw < 1.0:
            return
        self.last_draw = time.time()
        os.system("cls" if os.name == "nt" else "clear")
        if lines is not None:
            print("행  상태    흰/회   시간       (Ctrl+C 종료)")
            print(*lines, sep="\n"); print("-" * 44)
        if boss_lines is not None:
            print("보스:"); print(*boss_lines, sep="\n"); print("-" * 44)
        print(*self.events, sep="\n")


def boss_lines(br, bs):
    r = br.read
    if not r.present:
        return ["  바 없음"]
    out = [f"  바 x={r.anchor.text_x} y={r.anchor.text_y}  " + (f"띠 {len(r.slots)}칸" if r.has_strip else "띠 패널 없음 (구형 보스 → 감시 안 함)")]
    for s in r.slots:
        name = bs.icons.name(s.icon_id) if s.icon_id else "?"
        sec = f"={s.seconds}s" if s.seconds is not None else ("-" if s.label == "" else f"?{s.label}")
        out.append(f"  {s.index:2d} {name[:12]:<12} {s.label:>3} {sec}")
    if br.shown:
        out.append("  표시: " + ", ".join(f"{st.watch.label}{'' if not st.present else f'({st.seconds}s)'}" for st in br.shown))
    return out


def main(pick, recalib, debug, boss=False, boss_only=False):
    hwnd = find_window("마비노기")
    cx, cy, cw, ch = client_rect(hwnd)
    sx, sy, sw, sh = STATUS_RECT
    cap = Capture()
    con = Console()
    sess = None
    if not boss_only:
        sess = Session(cap, (cx + sx, cy + sy, sw, sh), STATUS_RECT, pid="_console", recalib=recalib, pick=pick,
                       watch_opts=None)
        for n in sess.notes:
            con.log(n)
        con.log(f"감시 {len(sess.tracker.tracks)}개 시작")
    bs = None
    if boss or boss_only:
        bs = BossSession(verbose=True, learn="--learn" in sys.argv)   # 감시 목록 없음: 인식만. --learn 이면 모르는 아이콘 등록
        con.log(f"보스 띠 감시 (아이콘 {len(bs.icons.items)}종 등록됨)")
    bx, by, bw, bh = BOSS_RECT
    use_full = bs is not None                  # 영역 둘 이상이면 전체 1회 캡처 후 자름 (dxcam 새 프레임 소비 문제)

    while True:
        t0 = time.time()
        if use_full:
            full = cap.grab((cx, cy, cw, ch))
            frame = None if full is None else (full[sy:sy + sh, sx:sx + sw] if sess else full)
            bframe = None if full is None else full[by:by + bh, bx:bx + bw]
        else:
            frame, bframe = cap.grab(sess.region), None
        blines = None
        if bs is not None and bframe is not None:
            br = bs.process(bframe)
            for n in br.notes:
                con.log(n)
            for ev in br.events:
                con.log(f"[보스] {ev.label} {debuff_event_text(ev)}" if ev.label else f"[보스] {debuff_event_text(ev)}")
            blines = boss_lines(br, bs)
            if debug:
                vis = bframe.copy()
                if br.read.present:
                    a = br.read.anchor
                    cv2.rectangle(vis, (a.text_x - 1, a.text_y - 1), (a.pct_x1 + 1, a.text_y + 17), (0, 255, 255), 1)
                    for s in br.read.slots:
                        cv2.rectangle(vis, (s.x, s.y), (s.x + 13, s.y + 13), (0, 255, 0) if s.icon_id else (0, 0, 255), 1)
                cv2.imshow("boss (b: save)", cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
        if sess is None:
            con.draw(None, blines)
            if debug:
                key = cv2.waitKey(1) & 0xFF
                if key == ord("b") and bframe is not None:
                    con.log(f"보스 영역 저장 {bs.save_frame(bframe)}")
                elif key == ord("q"):
                    debug = False; cv2.destroyAllWindows()
            time.sleep(max(0, 1 / FPS - (time.time() - t0)))
            continue
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
            con.draw(lines, blines)

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
                elif key == ord("b") and bframe is not None:
                    con.log(f"보스 영역 저장 {bs.save_frame(bframe)}")
        time.sleep(max(0, 1 / FPS - (time.time() - t0)))


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        main([int(a) for a in args if a.isdigit()], "--recalib" in args, "--debug" in args,
             boss="--boss" in args, boss_only="--bossonly" in args)
    except KeyboardInterrupt:
        print("\n종료")