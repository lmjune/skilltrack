"""
보스 디버프 오버레이. 감시 목록 중 '빠진' 디버프와 '곧 끝나는'(임계 이하) 디버프를 아이콘 + 이름으로 나열하는 창 하나.
빠짐 = 붉은 테두리, 곧 끝남 = 노란 테두리 + 남은 초. 목록이 비면(전부 걸려 있음) 아무것도 안 그린다.
편집 모드: 드래그 이동, 휠 배율 (아이콘 12px × 배율).
"""
import cv2
import numpy as np
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap

from core.bossbar import INNER
from win.alert_overlay import EditableOverlay

PAD = 6


class BossOverlay(EditableOverlay):
    def __init__(self, icons, pos=(1500, 1150), scale=3.0, opacity=0.95):
        super().__init__()
        self._init_editable("보스 디버프")
        self.icons = icons                    # IconLib (아이콘 그림 + 이름)
        self.scale = float(scale)
        self.rows = []                        # [(icon_id, name, remaining|None)]
        self._pix = {}
        self._ck = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowOpacity(opacity)
        self.move(int(pos[0]), int(pos[1]))
        self._resize(); self.show(); self._apply_flags()

    # ---- 크기
    @property
    def cell(self):
        return int(INNER * self.scale)

    def _resize(self):
        n = max(len(self.rows), 1 if self.edit_mode else 0)
        w = int(self.cell + 8 + 7 * self.cell)             # 아이콘 + 이름/시간 글자 공간
        h = n * (self.cell + PAD) + PAD + (26 if self.edit_mode else 0)
        self.resize(max(w, 120), max(h, 20))

    def set_scale(self, s):
        self.scale = max(1.0, min(8.0, float(s))); self._pix = {}; self._resize(); self.update(); self.moved.emit()

    def on_wheel(self, step):
        self.set_scale(self.scale + 0.25 * step)

    def set_edit(self, on):
        super().set_edit(on); self._resize(); self.update()

    # ---- 내용
    def update_from(self, states, now=None):
        """states: [DebuffState] (BossTracker.shown). 이름·남은 초로 행을 만든다."""
        import time
        now = time.time() if now is None else now
        rows = []
        for st in states:
            rem = st.remaining(now) if st.present else None
            rows.append((st.watch.icon_id, st.watch.label, rem))
        ck = tuple((k, n, None if r is None else r) for k, n, r in rows)
        if ck == self._ck:
            return
        self._ck, self.rows = ck, rows
        self._resize(); self.update()

    def _pixmap(self, icon_id):
        if icon_id not in self._pix:
            img = self.icons.items.get(icon_id)
            if img is None:
                img = np.zeros((INNER, INNER, 3), np.uint8)
            rgb = cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_BGR2RGB)
            qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
            self._pix[icon_id] = QPixmap.fromImage(qi).scaled(self.cell, self.cell, Qt.KeepAspectRatio, Qt.FastTransformation)
        return self._pix[icon_id]

    def paintEvent(self, _):
        p = QPainter(self)
        self._paint_edit_frame(p)
        rows = self.rows or ([("", "빠진 디버프 (예시)", None)] if self.edit_mode else [])
        c = self.cell
        font = QFont("Malgun Gothic", max(9, int(c * 0.45)), QFont.Bold)
        p.setFont(font)
        y = PAD
        for icon_id, name, rem in rows:
            missing = rem is None
            col = QColor(255, 80, 80) if missing else QColor(255, 200, 60)
            # 바탕
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(QRectF(0, y - 2, self.width(), c + 4), 6, 6)
            # 아이콘 + 테두리
            if icon_id:
                p.drawPixmap(PAD, y, self._pixmap(icon_id))
            p.setPen(QPen(col, 2)); p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(PAD - 1, y - 1, c + 2, c + 2))
            # 글자 (검은 외곽선 흉내: 아래·오른쪽에 그림자)
            text = f"{name}  {'빠짐' if missing else f'{rem}초'}"
            r = QRectF(PAD + c + 8, y, self.width() - c - 16, c)
            p.setPen(QColor(0, 0, 0)); p.drawText(r.translated(1, 1), Qt.AlignLeft | Qt.AlignVCenter, text)
            p.setPen(col); p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, text)
            y += c + PAD
        p.end()