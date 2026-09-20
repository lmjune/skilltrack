"""상태 미러: 버프 행마다 MirrorItem. 아이콘/이름/시간 조각을 이어 붙여 표시."""
import numpy as np

from win.mirror import MirrorItem, MirrorGroup

TIME_W = 80


class RowOpt:
    def __init__(self, row, icon=True, name=True, time=True, only_active=False, dim_inactive=True, pos=None, scale=None):
        self.row, self.icon, self.name, self.time = row, icon, name, time
        self.only_active, self.dim_inactive, self.pos, self.scale = only_active, dim_inactive, pos, scale


class StatusMirrorGroup(MirrorGroup):
    def __init__(self, layout, opts, default_scale=2.0, opacity=0.95, origin=(1500, 1300), labels=None):
        super().__init__()
        self.layout, self.opts = layout, {}
        for o in opts:
            title = (labels or {}).get(o.row, f"행 {o.row}")
            it = MirrorItem(("status", o.row), title, o.scale or default_scale, opacity,
                            base_size=(layout.icon_w + 4 + TIME_W + 60, layout.icon_h), dim_inactive=o.dim_inactive)
            self.add(it, o.pos, origin); self.opts[o.row] = o

    def update_from(self, frame, result):
        L = self.layout
        states = {s.index: s for s in result.states}
        for it in self.items:
            o = self.opts[it.key[1]]; s = states.get(o.row)
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