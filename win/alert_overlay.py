"""
알림 오버레이: 투명·클릭 통과·항상 위 창에 토스트 메시지를 띄운다. 몇 초 뒤 페이드아웃.
소리는 winsound (파일 없으면 심각도별 비프).

    ov = AlertOverlay(pos=(1600, 200), width=520)
    ov.push("마나실드 꺼짐", level="danger")
"""
import ctypes
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11

LEVEL_COLOR = {          # 배경, 글자
    "danger": (QColor(180, 30, 30, 230), QColor(255, 255, 255)),
    "warn":   (QColor(200, 120, 0, 230), QColor(255, 255, 255)),
    "info":   (QColor(30, 90, 160, 220), QColor(255, 255, 255)),
    "ok":     (QColor(30, 130, 60, 220), QColor(255, 255, 255)),
}
LEVEL_BEEP = {"danger": (880, 350), "warn": (660, 250), "info": (520, 150), "ok": (440, 120)}


@dataclass
class Toast:
    text: str
    level: str
    born: float
    duration: float


class AlertOverlay(QWidget):
    def __init__(self, pos=(1600, 200), width=520, row_h=48, max_rows=6, font_pt=18):
        super().__init__()
        self.toasts: list[Toast] = []
        self.row_h, self.max_rows, self.width_ = row_h, max_rows, width
        self.font_ = QFont("Malgun Gothic", font_pt, QFont.Bold)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(pos[0], pos[1], width, row_h * max_rows + 8)
        self.show()
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    # ------------------------------------------------------------ API
    def push(self, text, level="info", duration=4.0, sound=True, sound_file=None):
        # 같은 문구가 이미 떠 있으면 시간만 연장 (스팸 방지)
        for t in self.toasts:
            if t.text == text:
                t.born = time.time(); t.duration = duration
                return
        self.toasts.append(Toast(text, level, time.time(), duration))
        self.toasts = self.toasts[-self.max_rows:]
        if sound:
            play_sound(level, sound_file)
        self.update()

    # ------------------------------------------------------------ 내부
    def _tick(self):
        now = time.time()
        alive = [t for t in self.toasts if now - t.born < t.duration]
        if len(alive) != len(self.toasts) or alive:
            self.toasts = alive
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.font_)
        now = time.time()
        for i, t in enumerate(self.toasts):
            left = t.duration - (now - t.born)
            alpha = max(0.0, min(1.0, left / 0.6))          # 마지막 0.6초 페이드
            bg, fg = LEVEL_COLOR.get(t.level, LEVEL_COLOR["info"])
            bg = QColor(bg); bg.setAlphaF(bg.alphaF() * alpha)
            fg = QColor(fg); fg.setAlphaF(alpha)
            rect = QRectF(4, 4 + i * self.row_h, self.width_ - 8, self.row_h - 6)
            p.setPen(Qt.NoPen); p.setBrush(bg); p.drawRoundedRect(rect, 8, 8)
            p.setPen(QPen(fg)); p.drawText(rect.adjusted(14, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft, t.text)
        p.end()


def play_sound(level="info", sound_file=None):
    try:
        import winsound
        if sound_file and Path(sound_file).exists():
            winsound.PlaySound(str(sound_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            f, ms = LEVEL_BEEP.get(level, LEVEL_BEEP["info"])
            winsound.Beep(f, ms)
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    screen = app.primaryScreen().geometry()
    print("화면(논리 좌표):", screen.width(), "x", screen.height(), " DPI 배율:", app.primaryScreen().devicePixelRatio())
    pos = (screen.width() // 2 - 260, screen.height() // 3)
    ov = AlertOverlay(pos=pos)
    print("오버레이 창 생성:", ov.geometry(), " visible:", ov.isVisible())
    seq = [("마나실드 꺼짐", "danger"), ("전장의 서곡 30초 미만", "warn"), ("전장의 서곡 연장됨", "info"), ("엘레멘탈 부여 켜짐", "ok")]

    def show(i):
        txt, lv = seq[i]
        ov.push(txt, lv, duration=6.0)
        print(f"토스트 {i + 1}/4 표시: {txt}  (현재 {len(ov.toasts)}개, visible={ov.isVisible()})")

    for i in range(len(seq)):
        QTimer.singleShot(1000 * (i + 1), lambda i=i: show(i))
    print("창이 화면 가운데 위쪽에 떠야 합니다. 종료: Ctrl+C")
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    ka = QTimer(); ka.timeout.connect(lambda: None); ka.start(200)
    sys.exit(app.exec())