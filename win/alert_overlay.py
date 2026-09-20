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

from PySide6.QtCore import Qt, QTimer, QRectF, Signal, QPoint
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11
CAPTURABLE = {"on": False}      # True 면 오버레이가 스크린샷에 찍힘 (가이드 작성용). 일반 설정에서 토글
_ALL = []                        # 살아 있는 오버레이 창들 (설정 바뀔 때 일괄 적용)


def set_capturable(on: bool):
    CAPTURABLE["on"] = bool(on)
    for w in list(_ALL):
        try:
            w._apply_affinity()
        except RuntimeError:
            _ALL.remove(w)

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


FLAGS_RUN = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput
FLAGS_EDIT = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool


class EditableOverlay(QWidget):
    """편집 모드 공통: 클릭 통과를 풀고 드래그로 창을 옮긴다. 테두리와 제목을 그린다.
    Shift+드래그 = 그룹 이동 신호(group_drag), Shift+휠 = 그룹 배율 신호(group_wheel)."""
    moved = Signal()
    group_drag = Signal(int, int)      # dx, dy
    group_wheel = Signal(int)          # +1 / -1

    def _init_editable(self, title):
        self.edit_title = title
        self.edit_mode = False
        self._drag = None
        _ALL.append(self)

    def _apply_affinity(self):
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0 if CAPTURABLE["on"] else WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def _apply_flags(self):
        vis = self.isVisible()
        self.setWindowFlags(FLAGS_EDIT if self.edit_mode else FLAGS_RUN)
        if vis:
            self.show()
        self._apply_affinity()

    def set_edit(self, on: bool):
        self.edit_mode = on
        self._apply_flags()
        self.update()

    def mousePressEvent(self, e):
        if self.edit_mode and e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.edit_mode and self._drag is not None:
            new = e.globalPosition().toPoint() - self._drag
            d = new - self.pos()
            if e.modifiers() & Qt.ShiftModifier:
                self.group_drag.emit(d.x(), d.y())
            else:
                self.move(new); self.moved.emit()

    def wheelEvent(self, e):
        if not self.edit_mode:
            return
        step = 1 if e.angleDelta().y() > 0 else -1
        if e.modifiers() & Qt.ShiftModifier:
            self.group_wheel.emit(step)
        else:
            self.on_wheel(step)

    def on_wheel(self, step):
        pass

    def mouseReleaseEvent(self, e):
        self._drag = None

    def _paint_edit_frame(self, p: QPainter):
        if not self.edit_mode:
            return
        p.setPen(QPen(QColor(91, 140, 255), 2, Qt.DashLine)); p.setBrush(QColor(91, 140, 255, 30))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)
        p.setPen(QPen(QColor(255, 255, 255)))
        p.setFont(QFont("Malgun Gothic", 11, QFont.Bold))
        p.drawText(QRectF(10, self.height() - 26, self.width() - 20, 22), Qt.AlignLeft | Qt.AlignVCenter, f"{self.edit_title} — 드래그로 이동")


class AlertOverlay(EditableOverlay):
    def __init__(self, pos=(1600, 200), width=520, row_h=48, max_rows=6, font_pt=18):
        super().__init__()
        self._init_editable("알림")
        self.toasts: list[Toast] = []
        self.row_h, self.max_rows, self.width_ = row_h, max_rows, width
        self.font_ = QFont("Malgun Gothic", font_pt, QFont.Bold)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(pos[0], pos[1], width, row_h * max_rows + 8)
        self.show()
        self._apply_flags()
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
        self._paint_edit_frame(p)
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


SOUND_DIR = Path(__file__).parent.parent / "assets" / "sounds"   # 기본 알림음 (직접 합성, 라이선스 없음)
LEVEL_FILE = {"danger": "danger.wav", "warn": "warn.wav", "info": "info.wav", "ok": "info.wav"}


def play_sound(level="info", sound_file=None):
    """사용자 지정 wav → 없으면 심각도별 기본 wav → 그것도 없으면 비프."""
    try:
        import winsound
        path = Path(sound_file) if sound_file else SOUND_DIR / LEVEL_FILE.get(level, "info.wav")
        if path.exists():
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
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