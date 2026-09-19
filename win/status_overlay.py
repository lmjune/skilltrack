"""
상태 미러 오버레이: 선택한 버프 행의 아이콘 / 이름 / 시간 이미지를 원하는 위치에 확대 표시.

행마다 옵션:
  icon, name, time : 각각 표시 여부
  only_active      : True 면 활성일 때만 표시 (비활성이면 자리 비움), False 면 항상
  dim_inactive     : 항상 표시할 때 비활성이면 반투명으로

프레임과 세션 결과(Result)를 받아 그린다. 인식은 하지 않는다.
"""
import ctypes
from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11
TIME_W = 80          # 시간 영역 폭 (time_right 왼쪽으로). '25분 35초' 가 46px 이므로 여유


@dataclass
class RowOpt:
    row: int
    icon: bool = True
    name: bool = True
    time: bool = True
    only_active: bool = False
    dim_inactive: bool = True


class StatusOverlay(QWidget):
    def __init__(self, layout, opts: list[RowOpt], pos=(1500, 1300), scale=2.0, gap=8, opacity=0.95):
        super().__init__()
        self.layout_, self.opts, self.scale, self.gap = layout, opts, scale, gap
        self.rows_data = {}          # row → (QPixmap, active, key)
        self._last_key = {}

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowOpacity(opacity)

        h = layout.icon_h
        self.row_px = int(h * scale) + gap
        w = int((layout.icon_w + 4 + (layout.time_right or layout.right) - layout.text_x) * scale)
        self.setGeometry(pos[0], pos[1], w, self.row_px * len(opts))
        self.show()
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    # ------------------------------------------------------------ 갱신
    def update_from(self, frame, result):
        """frame: 상태창 크롭, result: Session.process 결과"""
        L = self.layout_
        states = {s.index: s for s in result.states}
        changed = False
        for o in self.opts:
            s = states.get(o.row)
            if s is None or o.row >= len(L.rows):
                continue
            r = L.rows[o.row]
            rd = result.readings.get(o.row)
            active = rd.state == "on" if rd else bool(s.active)
            if o.only_active and not active:
                if o.row in self.rows_data:
                    del self.rows_data[o.row]; changed = True
                continue

            parts = []
            if o.icon:
                x, y, w, h = r.icon
                parts.append(frame[y:y + h, x:x + w])
            if o.name and s.name_range:
                x, y, w, h = r.text
                a, b = s.name_range
                parts.append(frame[y:y + h, x + a:x + b + 1])
            if o.time:
                x, y, w, h = r.text
                tr = L.time_right if L.time_right is not None else L.right
                parts.append(frame[y:y + h, max(x, tr - TIME_W):tr + 4])

            if not parts:
                continue
            H = max(p.shape[0] for p in parts)
            canvas = np.zeros((H, sum(p.shape[1] for p in parts) + 4 * (len(parts) - 1), 3), np.uint8)
            cx = 0
            for p in parts:
                canvas[:p.shape[0], cx:cx + p.shape[1]] = p
                cx += p.shape[1] + 4
            key = (canvas.shape, int(canvas[::3, ::3].sum()), active)   # 값이 안 바뀌면 다시 안 그림
            if self._last_key.get(o.row) == key:
                continue
            self._last_key[o.row] = key
            rgb = cv2.cvtColor(np.ascontiguousarray(canvas), cv2.COLOR_BGR2RGB)
            qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
            self.rows_data[o.row] = (QPixmap.fromImage(qi), active)
            changed = True
        if changed:
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        for i, o in enumerate(self.opts):
            d = self.rows_data.get(o.row)
            if d is None:
                continue
            pm, active = d
            p.setOpacity(1.0 if active or not o.dim_inactive else 0.35)
            p.drawPixmap(0, i * self.row_px, int(pm.width() * self.scale), int(pm.height() * self.scale), pm)
        p.end()