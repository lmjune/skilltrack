"""
미러 항목/그룹 공용. 항목 = 화면 어딘가의 작은 조각을 확대해 보여주는 독립 창.
상태 행(버프)과 스킬 슬롯이 같은 클래스를 쓴다. 편집: 드래그/휠 = 개별, Shift = 그룹.
"""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap

from win.alert_overlay import EditableOverlay

GAP = 6


class MirrorItem(EditableOverlay):
    def __init__(self, key, title, scale, opacity, base_size=(40, 40), dim_inactive=True):
        super().__init__()
        self._init_editable(title)
        self.key, self.pix, self.active, self._ck = key, None, True, None
        self.base_w, self.base_h, self.dim_inactive = base_size[0], base_size[1], dim_inactive
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowOpacity(opacity)
        self.scale = scale
        self._resize()
        self.show(); self._apply_flags()

    def _resize(self):
        w = int((self.pix.width() if self.pix else self.base_w) * self.scale)
        h = int((self.pix.height() if self.pix else self.base_h) * self.scale)
        self.resize(max(w, 24), max(h, 16) + (26 if self.edit_mode else 0))

    def set_scale(self, s):
        self.scale = max(0.5, min(6.0, float(s))); self._resize(); self.update(); self.moved.emit()

    def on_wheel(self, step):
        self.set_scale(self.scale + 0.1 * step)

    def set_edit(self, on):
        super().set_edit(on); self._resize()

    def set_content(self, bgr, active=True):
        ck = (bgr.shape, int(bgr[::3, ::3].sum()), active)
        if ck == self._ck:
            return
        self._ck, self.active = ck, active
        rgb = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2RGB)
        qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
        self.pix = QPixmap.fromImage(qi); self._resize(); self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self._paint_edit_frame(p)
        if self.pix:
            p.setOpacity(1.0 if self.active or not self.dim_inactive else 0.35)
            p.drawPixmap(0, 0, int(self.pix.width() * self.scale), int(self.pix.height() * self.scale), self.pix)
        p.end()


class MirrorGroup:
    """항목 묶음. 그룹 이동/배율, 표시/편집, 위치 저장."""

    def __init__(self):
        self.items = []
        self._shown = True

    def add(self, item, pos=None, origin=(1500, 1300)):
        if pos:
            item.move(int(pos[0]), int(pos[1]))
        else:
            last = self.items[-1] if self.items else None
            item.move(last.x() if last else origin[0], (last.y() + last.height() + GAP) if last else origin[1])
        item.group_drag.connect(self._group_move); item.group_wheel.connect(self._group_scale)
        self.items.append(item)
        return item

    def set_visible(self, on):
        self._shown = on
        for it in self.items:
            it.setVisible(on)

    def set_edit(self, on):
        for it in self.items:
            it.set_edit(on)
            if on:
                it.setVisible(True)

    def set_scale_all(self, s):
        for it in self.items:
            it.set_scale(s)

    def set_opacity_all(self, o):
        for it in self.items:
            it.setWindowOpacity(o)

    def stack_vertical(self):
        if not self.items:
            return
        x, y = self.items[0].x(), self.items[0].y()
        for it in self.items:
            it.move(x, y); y += it.height() - (26 if it.edit_mode else 0) + GAP

    def _group_move(self, dx, dy):
        for it in self.items:
            it.move(it.x() + dx, it.y() + dy)

    def _group_scale(self, step):
        for it in self.items:
            it.set_scale(it.scale + 0.1 * step)

    def positions(self):
        return [(it.key, [it.x(), it.y()], round(it.scale, 2)) for it in self.items]

    def restore(self, saved):
        for it, (_, pos, sc) in zip(self.items, saved):
            it.move(*pos); it.set_scale(sc)

    def close(self):
        for it in self.items:
            it.close()
        self.items = []