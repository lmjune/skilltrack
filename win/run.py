"""
실행: 상태창 감시 + 알림 오버레이 + 상태 미러. 설정은 profiles/config.json.

사용법: python win/run.py [--recalib] [--no-sound]
종료:   터미널 Ctrl+C

처음 실행이면 config.json 이 기본값으로 생성된다. 상태창 영역(regions.status)은 3b 드래그 UI 로 채우거나
당장은 파일을 열어 [x, y, w, h] 를 적으면 된다 (클라이언트 기준).
"""
import signal
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import Config, CONFIG_FILE
from win.session import Session, FrameSaver, event_text, ROOT
from win.alert_overlay import AlertOverlay
from win.status_overlay import StatusOverlay, RowOpt
from win.window import find_window, client_rect

LEVEL = {"off": ("danger", 6), "keep": ("danger", 5), "under": ("warn", 5), "lost": ("warn", 5),
         "on": ("ok", 3), "extended": ("info", 3), "unextended": ("info", 3)}


def main(recalib, sound_override):
    app = QApplication(sys.argv)
    from win.capture import Capture      # dxcam 은 QApplication 뒤에 (DPI 경고 방지)

    cfg = Config.load()
    if not CONFIG_FILE.exists():
        cfg.save()
        print(f"설정 파일 생성: {CONFIG_FILE}")
    if not cfg.regions.status:
        print("상태창 영역이 설정되지 않았습니다. config.json 의 regions.status 에 [x, y, w, h] 를 적거나 "
              "영역 설정 UI(3b)를 사용하세요. 예: [2880, 1230, 300, 550]")
        return
    g = cfg.general
    sound = g.sound if sound_override is None else sound_override

    hwnd = find_window(g.window_title)
    if not hwnd:
        print(f"게임 창을 못 찾음: '{g.window_title}'"); return
    cx, cy, _, _ = client_rect(hwnd)
    sx, sy, sw, sh = cfg.regions.status
    cap = Capture()
    saver = FrameSaver(ROOT / "tests" / "fixtures" / "auto", enabled=g.diag_save)
    sess = Session(cap, (cx + sx, cy + sy, sw, sh), tuple(cfg.regions.status), recalib=recalib,
                   watch_opts=cfg.watch_opts(), saver=saver)
    for n in sess.notes:
        print(n)

    ov = cfg.overlays
    overlay = AlertOverlay(pos=tuple(ov.alert_pos), width=ov.alert_width, font_pt=ov.alert_font_pt)
    overlay.push("skilltrack 감시 시작", "info", 2.5, sound=False)
    mirror = None
    if ov.mirror_rows:
        opts = [RowOpt(m.row, m.icon, m.name, m.time, m.only_active, m.dim_inactive) for m in ov.mirror_rows]
        mirror = StatusOverlay(sess.layout, opts, pos=tuple(ov.mirror_pos), scale=ov.mirror_scale, opacity=ov.mirror_opacity)

    def tick():
        frame = cap.grab(sess.region)
        if frame is None:
            return
        r = sess.process(frame)
        if mirror:
            mirror.update_from(frame, r)
        for n in r.notes:
            print(f"[{datetime.now():%H:%M:%S}] {n}")
        for ev in r.events:
            if ev.kind not in LEVEL:
                continue
            level, dur = LEVEL[ev.kind]
            text = f"{ev.label} {event_text(ev)}"
            print(f"[{datetime.now():%H:%M:%S}] {text}")
            overlay.push(text, level, dur, sound=sound, sound_file=g.sound_file or None)

    timer = QTimer(); timer.timeout.connect(tick); timer.start(int(1000 / g.fps))
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    keepalive = QTimer(); keepalive.timeout.connect(lambda: None); keepalive.start(200)
    print("실행 중. Ctrl+C 로 종료")
    sys.exit(app.exec())


if __name__ == "__main__":
    args = sys.argv[1:]
    main("--recalib" in args, False if "--no-sound" in args else None)