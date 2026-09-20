"""
상태 미러: 버프 행마다 독립된 작은 창. 각자 위치·배율을 가진다.

  group = StatusMirrorGroup(layout, opts, default_scale, opacity)
  group.update_from(frame, result)     매 프레임
  group.set_edit(True/False)           편집: 개별 드래그/휠, Shift = 전부

RowOpt: row, icon, name, time, only_active, dim_inactive, pos, scale
"""
import cv2
import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from win.alert_overlay import EditableOverlay

TIME_W = 80
GAP = 6


class RowOpt:
    def __init__(self, row, icon=True, name=True, time=True, only_active=False, dim_inactive=True, pos=None, scale=None):
        self.row, self.icon, self.name, self.time = row, icon, name, time
        self.only_active, self.dim_inactive, self.pos, self.scale = only_active, dim_inactive, pos, scale


class StatusItem(EditableOverlay):
    def __init__(self, opt: RowOpt, layout, scale, opacity, title):
        super().__init__()
        self._init_editable(title)
        self.opt, self.layout_ = opt, layout
        self.pix, self.active, self._key = None, True, None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowOpacity(opacity)
        self.scale = scale
        L = layout
        self.base_w = L.icon_w + 4 + TIME_W + 4 + (L.right - L.text_x)   # 넉넉히; 실제 픽스맵 크기로 다시 잡음
        self.base_h = L.icon_h
        self._resize()
        self.show(); self._apply_flags()

    def _resize(self):
        w = int((self.pix.width() if self.pix else self.base_w) * self.scale)
        h = int((self.pix.height() if self.pix else self.base_h) * self.scale)
        self.resize(max(w, 40), max(h, 16) + (26 if self.edit_mode else 0))

    def set_scale(self, s):
        self.scale = max(0.5, min(6.0, float(s))); self._resize(); self.update(); self.moved.emit()

    def on_wheel(self, step):
        self.set_scale(self.scale + 0.1 * step)

    def set_edit(self, on):
        super().set_edit(on); self._resize()

    def set_content(self, bgr, active):
        key = (bgr.shape, int(bgr[::3, ::3].sum()), active)
        if key == self._key:
            return
        self._key, self.active = key, active
        rgb = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2RGB)
        qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
        self.pix = QPixmap.fromImage(qi); self._resize(); self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self._paint_edit_frame(p)
        if self.pix:
            p.setOpacity(1.0 if self.active or not self.opt.dim_inactive else 0.35)
            p.drawPixmap(0, 0, int(self.pix.width() * self.scale), int(self.pix.height() * self.scale), self.pix)
        p.end()


class StatusMirrorGroup:
    def __init__(self, layout, opts, default_scale=2.0, opacity=0.95, origin=(1500, 1300), labels=None):
        self.layout, self.items = layout, []
        y = origin[1]
        for o in opts:
            title = (labels or {}).get(o.row, f"행 {o.row}")
            it = StatusItem(o, layout, o.scale or default_scale, opacity, title)
            if o.pos:
                it.move(int(o.pos[0]), int(o.pos[1]))
            else:
                it.move(origin[0], y); y += it.height() + GAP
            it.group_drag.connect(self._group_move); it.group_wheel.connect(self._group_scale)
            self.items.append(it)

    # ---- 프레임 반영 ----
    def update_from(self, frame, result):
        L = self.layout
        states = {s.index: s for s in result.states}
        for it in self.items:
            o = it.opt; s = states.get(o.row)
            if s is None or o.row >= len(L.rows):
                continue
            r = L.rows[o.row]; rd = result.readings.get(o.row)
            active = rd.state == "on" if rd else bool(s.active)
            if o.only_active and not active and not it.edit_mode:
                it.setVisible(False); continue
            parts = []
            if o.icon:
                x, y, w, h = r.icon; parts.append(frame[y:y + h, x:x + w])
            if o.name and s.name_range:
                x, y, w, h = r.text; a, b = s.name_range; parts.append(frame[y:y + h, x + a:x + b + 1])
            if o.time:
                x, y, w, h = r.text; tr = L.time_right if L.time_right is not None else L.right
                parts.append(frame[y:y + h, max(x, tr - TIME_W):tr + 4])
            if not parts:
                continue
            H = max(p.shape[0] for p in parts)
            canvas = np.zeros((H, sum(p.shape[1] for p in parts) + 4 * (len(parts) - 1), 3), np.uint8)
            cx = 0
            for p in parts:
                canvas[:p.shape[0], cx:cx + p.shape[1]] = p; cx += p.shape[1] + 4
            it.set_content(canvas, active)
            if not it.isVisible() and self._shown:
                it.setVisible(True)

    # ---- 표시/편집 ----
    _shown = True

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
        """첫 항목 아래로 나머지를 세로 정렬"""
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
        """[(row, [x, y], scale)]"""
        return [(it.opt.row, [it.x(), it.y()], round(it.scale, 2)) for it in self.items]

    def close(self):
        for it in self.items:
            it.close()
        self.items = []