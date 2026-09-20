"""
스킬 미러: 스킬창 슬롯마다 MirrorItem. 캡처는 스킬창 영역 단위로 한 번씩 하고 슬롯을 잘라 쓴다.
표시 모드: always(항상) / cooling(쿨 중에만) / dimmed(항상, 준비되면 흐리게)
"""
from core.cooldown import SlotCooldown
from win.mirror import MirrorItem, MirrorGroup


class SkillMirrorGroup(MirrorGroup):
    def __init__(self, cap, client_xy, regions, items_cfg, default_scale=2.0, opacity=0.95, origin=(1500, 1500), smooth=True):
        """
        regions: profile.regions.skill (id, rect, grid). items_cfg: profile.skill_items
        """
        super().__init__()
        self.cap, self.cx, self.cy = cap, client_xy[0], client_xy[1]
        self.regions = {r["id"]: r for r in regions}
        self.cfg, self.cd = {}, {}
        for c in items_cfg:
            rg = self.regions.get(c.region)
            if not rg:
                continue
            g = rg["grid"]; cols = len(g["xs"])
            if c.slot >= cols * len(g["ys"]):
                continue
            it = MirrorItem(("skill", c.region, c.slot), f"{c.region} #{c.slot}", c.scale or default_scale, opacity,
                            base_size=(g["w"], g["h"]), dim_inactive=(c.mode == "dimmed"), smooth=smooth)
            self.add(it, c.pos, origin); self.cfg[it.key] = c; self.cd[it.key] = SlotCooldown()

    def slot_rect(self, region_id, slot):
        g = self.regions[region_id]["grid"]; cols = len(g["xs"])
        return g["xs"][slot % cols], g["ys"][slot // cols], g["w"], g["h"]

    def update(self, full=None):
        """full: 전체 화면 프레임 (있으면 거기서 잘라 씀. 없으면 영역별 grab)"""
        frames = {}
        for rid, rg in self.regions.items():
            if not any(k[1] == rid for k in self.cfg):
                continue
            x, y, w, h = rg["rect"]
            if full is not None:
                f = full[self.cy + y:self.cy + y + h, self.cx + x:self.cx + x + w]
            else:
                f = self.cap.grab((self.cx + x, self.cy + y, w, h))
            if f is not None and f.size:
                frames[rid] = (f, x, y)
        for it in self.items:
            _, rid, slot = it.key
            if rid not in frames:
                continue
            f, rx, ry = frames[rid]
            sx, sy, sw, sh = self.slot_rect(rid, slot)
            crop = f[sy - ry:sy - ry + sh, sx - rx:sx - rx + sw]
            if crop.size == 0:
                continue
            cooling = self.cd[it.key].update(crop)
            mode = self.cfg[it.key].mode
            if mode == "cooling" and not cooling and not it.edit_mode:
                it.setVisible(False); continue
            it.set_content(crop, active=cooling if mode == "dimmed" else True)
            if not it.isVisible() and self._shown:
                it.setVisible(True)