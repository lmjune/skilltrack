"""
앱 아이콘 (트레이·창·exe). 직접 그린 켈트풍 매듭 — 세잎 매듭(트레포일, 수학 곡선)을 엮어 그림.
마비노기 공식 로고를 따라 그린 것이 아님. 색은 따뜻한 주황 / 꺼짐은 회색.
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ORANGE, DIM = "#ff8a1f", "#8b919c"
BG = "#1f1d1b"


def _knot(cx, cy, size, n=480):
    """세잎 매듭 (트레포일): x = sin t + 2 sin 2t, y = cos t − 2 cos 2t, 높이 z = −sin 3t (어느 줄이 위로 지나가는지).
    (cx, cy) 가운데, 폭·높이 중 큰 쪽이 size 가 되게."""
    raw = []
    for i in range(n):
        t = 2 * math.pi * i / n
        raw.append((math.sin(t) + 2 * math.sin(2 * t), -(math.cos(t) - 2 * math.cos(2 * t)), -math.sin(3 * t)))
    xs, ys = [q[0] for q in raw], [q[1] for q in raw]
    k = size / max(max(xs) - min(xs), max(ys) - min(ys))
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [(cx + (x - mx) * k, cy + (y - my) * k, z) for x, y, z in raw]


def _cross(a, b, c, d):
    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) > (q[1] - p[1]) * (r[0] - p[0])
    return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)


def _path(pts, i0, i1):
    n = len(pts)
    path = QPainterPath(QPointF(*pts[i0 % n][:2]))
    for i in range(i0 + 1, i1 + 1):
        path.lineTo(QPointF(*pts[i % n][:2]))
    return path


def paint(p: QPainter, size: int, paused=False):
    s = size / 64.0
    col, bg = QColor(DIM if paused else ORANGE), QColor(BG)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen); p.setBrush(bg)
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)
    pts = _knot(32 * s, 32.5 * s, 41 * s)
    n = len(pts)
    w = 4.8 * s
    under = QPen(bg, w + 4.0 * s, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin)
    over = QPen(col, w, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin)
    whole = _path(pts, 0, n)
    p.setBrush(Qt.NoBrush)
    p.setPen(under); p.drawPath(whole)
    p.setPen(over); p.drawPath(whole)
    # 교차점마다 위에 있는 줄을 다시 그린다 (어두운 테두리가 아래 줄을 끊어 엮인 것처럼)
    k = n // 30
    done = set()
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 2 * k, i + n - 2 * k):
            jj = j % n
            c, d = pts[jj], pts[(jj + 1) % n]
            if _cross(a, b, c, d):
                top = i if a[2] > c[2] else jj
                key = top // k
                if key in done:
                    continue
                done.add(key)
                p.setPen(under); p.drawPath(_path(pts, top - k, top + k))
                p.setPen(over); p.drawPath(_path(pts, top - k - 3, top + k + 3))   # 색 선을 조금 더 길게 → 이음매 안 보이게


def make_icon(paused=False) -> QIcon:
    icon = QIcon()
    for n in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(n, n); pm.fill(Qt.transparent)
        p = QPainter(pm); paint(p, n, paused); p.end()
        icon.addPixmap(pm)
    return icon


def save_ico(path):
    """exe 아이콘 파일 만들기 (빌드 전 한 번): python -c "from win.app_icon import save_ico; save_ico('assets/icon.ico')" """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    pm = QPixmap(256, 256); pm.fill(Qt.transparent)
    p = QPainter(pm); paint(p, 256); p.end()
    pm.save(str(path).replace(".ico", ".png"))
    from PIL import Image
    Image.open(str(path).replace(".ico", ".png")).save(str(path), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
