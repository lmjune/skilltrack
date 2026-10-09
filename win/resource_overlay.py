"""
생명력/마나/스태미나 오버레이 두 가지.

ResourceOverlay — 자원 알림 칸 (기존 알림창과 별도). 부족한 동안 "생명력 25%" 를 계속 띄우고 회복하면 사라진다.
                  배치 편집에서 옮긴다.
EdgeOverlay     — 화면 가장자리 효과 (위·왼쪽·오른쪽 — 아래는 인식 영역이 몰려 있어 뺌). 부족한 자원 색(생명력 빨강·마나 파랑·스태미나 노랑)으로 테두리가 은은하게 숨쉬듯,
                  기준의 절반 이하(위험)면 진하고 빠르게. 클릭 통과, 캡처 제외 (인식에 안 섞인다).
"""
import math
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QLinearGradient, QGuiApplication, QRegion
from PySide6.QtWidgets import QWidget

from win.alert_overlay import EditableOverlay, FLAGS_RUN, _ALL, WDA_EXCLUDEFROMCAPTURE

COLOR = {"hp": QColor(235, 40, 70), "mp": QColor(60, 120, 255), "sp": QColor(240, 190, 30)}
NAMES = {"hp": "생명력", "mp": "마나", "sp": "스태미나"}


class ResourceOverlay(EditableOverlay):
    def __init__(self, pos=(1500, 1000), width=300, row_h=44, font_pt=18):
        super().__init__()
        self._init_editable("자원 알림")
        self.rows: list[tuple[str, int]] = []
        self.row_h = row_h
        self.font_ = QFont("Malgun Gothic", font_pt, QFont.Bold)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(pos[0], pos[1], width, row_h * 3 + 8)
        self.show()
        self._apply_flags()

    def set_rows(self, rows):
        rows = list(rows)
        if rows != self.rows:
            self.rows = rows
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_edit_frame(p)
        rows = self.rows if self.rows or not self.edit_mode else [("hp", 25), ("mp", 18)]   # 편집 중엔 예시
        p.setFont(self.font_)
        for i, (k, pct) in enumerate(rows):
            r = QRectF(4, 4 + i * self.row_h, self.width() - 8, self.row_h - 6)
            bg = QColor(COLOR[k]); bg.setAlpha(215)
            p.setPen(Qt.NoPen); p.setBrush(bg); p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor(255, 255, 255))
            p.drawText(r.adjusted(14, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, f"{NAMES[k]} {pct}%")
        p.end()


class EdgeOverlay(QWidget):
    """화면 가장자리 효과. levels = {key: 1 | 2} (비면 안 보임)."""

    THICK = 0.06        # 화면 짧은 변 대비 테두리 두께

    def __init__(self, strength=1.0):
        super().__init__(None, FLAGS_RUN)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.levels: dict = {}
        self.strength = strength
        self.holes: list = []        # 비워 둘 곳 (창 안 논리 좌표 QRect) — 인식 영역 (효과 색이 막대에 섞여 잘못 읽지 않게)
        self._cover_key = None
        self.t0 = time.time()
        self.timer = QTimer(self); self.timer.timeout.connect(self.update)
        _ALL.append(self)            # 캡처 포함/제외 설정을 다른 오버레이와 같이 따른다

    def _apply_affinity(self):
        import ctypes
        from win.alert_overlay import CAPTURABLE
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0 if CAPTURABLE["on"] else WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def cover(self, phys_rect, holes=()):
        """게임 창(물리 픽셀 x, y, w, h)이 있는 모니터 전체를 덮는다.
        holes: 화면 효과를 그리지 않을 곳 (물리 픽셀 x, y, w, h) — 인식 영역. 캡처 제외가 꺼져 있어도
        (일반 설정 '오버레이 캡처') 효과 색이 막대 위에 칠해져 잘못 읽는 일이 없게 (예전: 생명력 0%, 마나 100% 깜빡임)."""
        key = (tuple(phys_rect), tuple(map(tuple, holes)))
        if key == self._cover_key:
            return
        self._cover_key = key
        x, y, w, h = phys_rect
        best, bdpr = None, 1.0
        for s in QGuiApplication.screens():
            g, dpr = s.geometry(), s.devicePixelRatio()
            gx, gy, gw, gh = g.x() * dpr, g.y() * dpr, g.width() * dpr, g.height() * dpr
            cx, cy = x + w / 2, y + h / 2
            if gx <= cx < gx + gw and gy <= cy < gy + gh:
                best, bdpr = g, dpr
        if best is None:
            s = QGuiApplication.primaryScreen(); best, bdpr = s.geometry(), s.devicePixelRatio()
        self.setGeometry(best)
        ox, oy, pad = best.x() * bdpr, best.y() * bdpr, 12
        self.holes = [QRect(int((hx - ox) / bdpr) - pad, int((hy - oy) / bdpr) - pad,
                            int(hw / bdpr) + 2 * pad, int(hh / bdpr) + 2 * pad) for hx, hy, hw, hh in holes]
        self.update()

    def set_levels(self, levels: dict):
        if levels == self.levels:
            return
        was = bool(self.levels)
        self.levels = dict(levels)
        if self.levels and not was:
            self.t0 = time.time()
            self.show(); self._apply_affinity(); self.timer.start(40)   # 보일 때마다 다시 (창이 새로 만들어지면 풀린다)
        elif not self.levels and was:
            self.timer.stop(); self.hide()
        self.update()

    def paintEvent(self, _):
        if not self.levels:
            return
        p = QPainter(self)
        W, H = self.width(), self.height()
        if self.holes:
            clip = QRegion(0, 0, W, H)
            for r in self.holes:
                clip = clip.subtracted(QRegion(r))
            p.setClipRegion(clip)
        base = max(24.0, min(W, H) * self.THICK)
        t = time.time() - self.t0
        # 여러 자원이 부족하면 바깥부터 띠를 나눠 그린다 (생명력이 가장 바깥)
        order = [k for k in ("hp", "mp", "sp") if k in self.levels]
        for i, k in enumerate(order):
            lv = self.levels[k]
            speed = 2.4 if lv >= 2 else 1.2                       # 위험하면 빠르게
            amp = (0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * speed * math.pi)))
            alpha = int(min(255, (150 if lv >= 2 else 90) * amp * self.strength))
            off = i * base * 0.55
            th = base * (1.25 if lv >= 2 else 1.0)
            c0 = QColor(COLOR[k]); c0.setAlpha(alpha)
            c1 = QColor(COLOR[k]); c1.setAlpha(0)
            for side in ("top", "left", "right"):        # 아래 변은 안 그림 (자원 막대·보스 띠·스킬창이 다 아래쪽)
                if side == "top":
                    r = QRectF(0, off, W, th); g = QLinearGradient(0, off, 0, off + th)
                elif side == "bottom":
                    r = QRectF(0, H - off - th, W, th); g = QLinearGradient(0, H - off, 0, H - off - th)
                elif side == "left":
                    r = QRectF(off, 0, th, H); g = QLinearGradient(off, 0, off + th, 0)
                else:
                    r = QRectF(W - off - th, 0, th, H); g = QLinearGradient(W - off, 0, W - off - th, 0)
                g.setColorAt(0, c0); g.setColorAt(1, c1)
                p.fillRect(r, g)
        p.end()
