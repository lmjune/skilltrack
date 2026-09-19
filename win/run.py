"""
실행: 상태창 감시 + 알림 오버레이 (+ 선택: 스킬 미러). 콘솔엔 이벤트만.

사용법: python win/run.py [--recalib] [--no-sound]
종료:   터미널 Ctrl+C
"""
import signal
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent.parent))
from win.session import Session, event_text
from win.alert_overlay import AlertOverlay
from win.status_overlay import StatusOverlay, RowOpt
from win.window import find_window, client_rect
# win.capture (dxcam) 는 import 시점에 DPI 설정을 잡으므로 QApplication 뒤에서 import 한다

STATUS_RECT = (2880, 1230, 300, 550)
FPS = 5
ALERT_POS = (1500, 1500)       # 알림 좌상단 (화면 절대 좌표). 설정 UI 생기면 드래그로
KEEP_ROWS: set[int] = set()

# 상태 미러: 표시할 행과 옵션. 비우면 미러 없음. 설정 UI 생기면 체크로 대체
MIRROR_POS = (1500, 1300)
MIRROR_SCALE = 2.0
MIRROR_ROWS = [
    RowOpt(row=2, icon=True, name=True, time=True, only_active=False),   # 예: 전장의 서곡
    RowOpt(row=5, icon=True, name=True, time=False, only_active=False),  # 예: 마나실드
]

# 이벤트 → (심각도, 표시 시간). resync/found 는 표시 안 함
LEVEL = {"off": ("danger", 6), "keep": ("danger", 5), "under": ("warn", 5), "lost": ("warn", 5),
         "on": ("ok", 3), "extended": ("info", 3), "unextended": ("info", 3)}


def main(recalib, sound):
    app = QApplication(sys.argv)          # dxcam 보다 먼저: Qt 가 DPI 설정을 잡게 (경고 방지)
    from win.capture import Capture
    hwnd = find_window("마비노기")
    cx, cy, _, _ = client_rect(hwnd)
    sx, sy, sw, sh = STATUS_RECT
    cap = Capture()
    sess = Session(cap, (cx + sx, cy + sy, sw, sh), STATUS_RECT, recalib=recalib,
                   watch_opts={i: {"keep": True} for i in KEEP_ROWS})
    for n in sess.notes:
        print(n)

    overlay = AlertOverlay(pos=ALERT_POS)
    overlay.push("skilltrack 감시 시작", "info", 2.5, sound=False)
    mirror = StatusOverlay(sess.layout, MIRROR_ROWS, pos=MIRROR_POS, scale=MIRROR_SCALE) if MIRROR_ROWS else None

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
            overlay.push(text, level, dur, sound=sound)

    timer = QTimer(); timer.timeout.connect(tick); timer.start(int(1000 / FPS))
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    keepalive = QTimer(); keepalive.timeout.connect(lambda: None); keepalive.start(200)
    print("실행 중. Ctrl+C 로 종료")
    sys.exit(app.exec())


if __name__ == "__main__":
    args = sys.argv[1:]
    main("--recalib" in args, "--no-sound" not in args)