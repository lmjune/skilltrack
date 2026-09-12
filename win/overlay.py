"""
투명 · 클릭 통과 · 항상 위 · 캡처 제외 오버레이 창.
슬롯 rect 목록을 받아 주기적으로 캡처해서 확대 표시한다.
"""
import ctypes
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).parent.parent))
from win.capture import Capture

WDA_EXCLUDEFROMCAPTURE = 0x11


class MirrorOverlay(QWidget):
    def __init__(self, slots, scale=2.0, fps=10, pos=(1600, 1800), gap=6):
        """
        slots: [(x, y, w, h), ...]  화면 절대 좌표
        pos:   오버레이 좌상단 화면 좌표
        """
        super().__init__()
        self.slots = slots
        self.scale = scale
        self.gap = gap
        self.frames = [None] * len(slots)
        self.cap = Capture()

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # 오버레이 자체는 캡처에서 제외 (자기 자신을 다시 캡처하는 순환 방지)
        self._exclude_from_capture()

        w = int(sum(s[2] * scale for s in slots) + gap * (len(slots) - 1))
        h = int(max(s[3] for s in slots) * scale)
        self.setGeometry(pos[0], pos[1], w, h)

        # 슬롯들을 감싸는 최소 영역 하나만 캡처 → 슬라이싱
        xs = [s[0] for s in slots]; ys = [s[1] for s in slots]
        x1 = max(s[0] + s[2] for s in slots); y1 = max(s[1] + s[3] for s in slots)
        self.region = (min(xs), min(ys), x1 - min(xs), y1 - min(ys))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(int(1000 / fps))

    def _exclude_from_capture(self):
        self.show()  # winId 확보
        hwnd = int(self.winId())
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)

    def tick(self):
        frame = self.cap.grab(self.region)
        if frame is None:          # 변화 없음
            return
        rx, ry = self.region[0], self.region[1]
        for i, (x, y, w, h) in enumerate(self.slots):
            self.frames[i] = frame[y - ry:y - ry + h, x - rx:x - rx + w].copy()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)  # 픽셀 또렷하게
        cx = 0
        for f, (_, _, w, h) in zip(self.frames, self.slots):
            if f is not None:
                rgb = cv2.cvtColor(np.ascontiguousarray(f), cv2.COLOR_BGR2RGB)
                qi = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
                p.drawPixmap(cx, 0, int(w * self.scale), int(h * self.scale), QPixmap.fromImage(qi))
            cx += int(w * self.scale) + self.gap
        p.end()


if __name__ == "__main__":
    import signal
    from win.window import find_window, client_rect
    from core.grid import detect_grid_in

    hwnd = find_window("마비노기")
    cx, cy, cw, ch = client_rect(hwnd)
    full = Capture().grab_sure((cx, cy, cw, ch))
    g = detect_grid_in(full, (0, 0, 1230, 100))
    print(f"격자 {g.cols}x{g.rows}")

    WANT = [0, 4, 8, 12]
    rects = dict(g.all_slots())
    slots = [(cx + rects[i][0], cy + rects[i][1], rects[i][2], rects[i][3]) for i in WANT]

    app = QApplication(sys.argv)
    ov = MirrorOverlay(slots, scale=2.5, fps=10, pos=(1600, 1850))
    ov.show()

    # Ctrl+C 로 종료되게: 시그널을 기본 동작으로 돌리고, 파이썬이 시그널을 볼 틈을 줌
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(200)

    print("실행 중. 터미널에서 Ctrl+C 로 종료")
    sys.exit(app.exec())