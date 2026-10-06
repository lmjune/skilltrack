"""
가챠 덮개: 결과 화면을 가려두고 조금씩 줄여가며 확인하는 창 (긴장감용, 캐릭터와 무관).

- 홈의 [가챠 덮개] 버튼으로 켜고 끈다.
- 안쪽을 끌면 이동, 가장자리·모서리를 끌면 크기 조절. 휠을 굴리면 위에서부터 조금씩 줄어든다.
- 그림: 일반 설정의 '가챠 덮개 그림' (창에 꽉 차게, 넘치는 부분은 잘림). 없으면 어두운 단색.
- 위치·크기는 껐을 때 저장해 두고 다음에 그 자리에서 다시 뜬다.
"""
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QApplication

EDGE = 10            # 가장자리 잡는 폭 (px)
MIN_W, MIN_H = 40, 24
WHEEL_STEP = 12      # 휠 한 칸에 줄어드는 높이 (px)
BG = QColor(24, 26, 31)
HINT = QColor(140, 146, 158)


class GachaCover(QWidget):
    def __init__(self, image_path="", rect=None, on_moved=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_W, MIN_H)
        self.on_moved = on_moved
        self.pix = None
        self.set_image(image_path)
        if rect and len(rect) == 4 and rect[2] >= MIN_W and rect[3] >= MIN_H:
            self.setGeometry(QRect(*rect))
            self.ensure_visible()
        else:
            scr = QApplication.primaryScreen().availableGeometry()
            w, h = 600, 400
            self.setGeometry(scr.center().x() - w // 2, scr.center().y() - h // 2, w, h)
        self._drag = None          # (모드, 누른 전역 좌표, 누를 때 geometry)

    # ---------------------------------------------------------------- 그림
    def set_image(self, path):
        self.pix = None
        if path and Path(path).exists():
            p = QPixmap(str(path))
            if not p.isNull():
                self.pix = p
        self.update()

    def ensure_visible(self):
        """저장된 자리가 지금 모니터 밖이면 주 모니터 가운데로 (모니터 구성이 바뀐 경우)."""
        if any(s.geometry().intersects(self.geometry()) for s in QApplication.screens()):
            return
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.center() - self.rect().center())

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        if self.pix is not None:
            # 꽉 채우기 (비율 유지, 넘치는 쪽은 가운데 기준으로 잘림)
            sp = self.pix.scaled(r.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(0, 0, sp, (sp.width() - r.width()) // 2, (sp.height() - r.height()) // 2, r.width(), r.height())
        else:
            p.fillRect(r, BG)
            if r.width() >= 160 and r.height() >= 60:
                p.setPen(HINT)
                f = QFont(); f.setPixelSize(13); p.setFont(f)
                p.drawText(r, Qt.AlignCenter, "끌어서 이동 · 가장자리로 크기 조절 · 휠로 줄이기")
        p.setPen(QColor(255, 255, 255, 40))
        p.drawRect(r.adjusted(0, 0, -1, -1))           # 테두리 (어디까지가 덮개인지)

    # ---------------------------------------------------------------- 마우스
    def _zone(self, pos: QPoint) -> str:
        """누른 위치 → 'move' 또는 가장자리 조합 ('l','r','t','b','tl' …)."""
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        z = ("t" if y < EDGE else "b" if y >= h - EDGE else "") + ("l" if x < EDGE else "r" if x >= w - EDGE else "")
        return z or "move"

    CURSORS = {"move": Qt.SizeAllCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor,
               "b": Qt.SizeVerCursor, "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
               "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor}

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (self._zone(e.position().toPoint()), e.globalPosition().toPoint(), QRect(self.geometry()))

    def mouseMoveEvent(self, e):
        if self._drag is None:
            self.setCursor(self.CURSORS[self._zone(e.position().toPoint())])
            return
        mode, start, g0 = self._drag
        d = e.globalPosition().toPoint() - start
        if mode == "move":
            self.move(g0.topLeft() + d); return
        g = QRect(g0)
        if "l" in mode: g.setLeft(min(g0.left() + d.x(), g0.right() - MIN_W))
        if "r" in mode: g.setRight(max(g0.right() + d.x(), g0.left() + MIN_W))
        if "t" in mode: g.setTop(min(g0.top() + d.y(), g0.bottom() - MIN_H))
        if "b" in mode: g.setBottom(max(g0.bottom() + d.y(), g0.top() + MIN_H))
        self.setGeometry(g)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self._moved()

    def wheelEvent(self, e):
        """휠 아래로 = 위쪽부터 줄어듦 (한 줄씩 벗기기), 위로 = 다시 늘어남."""
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        g = QRect(self.geometry())
        g.setTop(min(g.top() - int(steps * WHEEL_STEP), g.bottom() - MIN_H))
        self.setGeometry(g)
        self._moved()

    def _moved(self):
        if self.on_moved:
            g = self.geometry()
            self.on_moved([g.x(), g.y(), g.width(), g.height()])
