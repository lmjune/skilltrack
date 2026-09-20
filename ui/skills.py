"""
스킬 표시 선택 창. 프로필의 스킬창 영역마다 슬롯 썸네일 격자를 보여주고, 표시할 슬롯을 체크 + 모드 선택.
저장하면 profile.skill_items.
"""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QCheckBox, QComboBox, QPushButton,
                               QScrollArea, QFrame)

from core.config import Config, SkillItem
from core.paths import APP_NAME

MODES = [("always", "항상 표시"), ("cooling", "쿨타임 중에만"), ("dimmed", "항상 (준비되면 흐리게)")]


def to_pixmap(bgr, scale=1.0):
    bgr = np.ascontiguousarray(bgr)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
    return QPixmap.fromImage(qi).scaled(int(rgb.shape[1] * scale), int(rgb.shape[0] * scale), Qt.KeepAspectRatio, Qt.FastTransformation)


class SlotCell(QFrame):
    def __init__(self, region_id, slot, thumb, existing: SkillItem | None):
        super().__init__()
        self.region_id, self.slot, self.existing = region_id, slot, existing
        self.setObjectName("card")
        v = QVBoxLayout(self); v.setContentsMargins(4, 4, 4, 4); v.setSpacing(2)
        pic = QLabel(); pic.setPixmap(thumb); pic.setAlignment(Qt.AlignCenter); v.addWidget(pic)
        self.on = QCheckBox(f"{slot}"); self.on.setObjectName("small"); self.on.setChecked(existing is not None); v.addWidget(self.on)
        self.mode = QComboBox(); self.mode.setFixedWidth(52)
        for key, label in (("always", "항상"), ("cooling", "쿨중"), ("dimmed", "흐림")):
            self.mode.addItem(label, key)
        self.mode.setToolTip("항상 = 항상 표시 · 쿨중 = 쿨타임 중에만 · 흐림 = 항상, 준비되면 흐리게")
        if existing:
            self.mode.setCurrentIndex([m[0] for m in MODES].index(existing.mode))
        self.mode.setEnabled(existing is not None); self.on.toggled.connect(self.mode.setEnabled)
        v.addWidget(self.mode)

    def item(self) -> SkillItem | None:
        if not self.on.isChecked():
            return None
        mode = self.mode.currentData()
        if self.existing:
            self.existing.mode = mode; return self.existing
        return SkillItem(region=self.region_id, slot=self.slot, mode=mode)


class SkillsWindow(QWidget):
    def __init__(self, cfg: Config, prof, frames: dict, on_saved=None, app=None):
        """frames: {region_id: (bgr, rx, ry)} 각 스킬창 영역 캡처. app: 영역 다시 지정/삭제용"""
        super().__init__()
        self.cfg, self.prof, self.on_saved, self.app = cfg, prof, on_saved, app
        self.setWindowTitle(APP_NAME); self.resize(1040, 720)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        head = QWidget(); hv = QVBoxLayout(head); hv.setContentsMargins(28, 24, 28, 12); hv.setSpacing(4)
        t = QLabel(f"스킬 표시 — {prof.name}"); t.setObjectName("title"); hv.addWidget(t)
        s = QLabel("화면에 크게 띄울 슬롯을 체크하세요. 모드: 항상 / 쿨중(쿨타임 중에만) / 흐림(준비되면 흐리게). 위치는 [배치 편집]에서."); s.setObjectName("subtitle"); hv.addWidget(s)
        root.addWidget(head)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); root.addWidget(scroll, 1)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(28, 8, 28, 16); v.setSpacing(14); scroll.setWidget(inner)

        existing = {(it.region, it.slot): it for it in prof.skill_items}
        self.cells = []
        for rg in prof.regions.skill:
            rid = rg["id"]; g = rg["grid"]; cols = len(g["xs"])
            hh = QHBoxLayout(); hh.setSpacing(10)
            sec = QLabel(f"{rid}  ({cols}x{len(g['ys'])})"); sec.setObjectName("section"); hh.addWidget(sec); hh.addStretch()
            if self.app:
                re = QPushButton("다시 지정"); re.setObjectName("ghost"); re.setToolTip("스킬창을 옮겼을 때"); re.clicked.connect(lambda _, r=rid: self._redo(r)); hh.addWidget(re)
                rm = QPushButton("삭제"); rm.setObjectName("ghost"); rm.clicked.connect(lambda _, r=rid: self._remove(r)); hh.addWidget(rm)
            v.addLayout(hh)
            grid = QGridLayout(); grid.setSpacing(4); grid.setAlignment(Qt.AlignLeft); v.addLayout(grid)
            fr = frames.get(rid)
            for r, y in enumerate(g["ys"]):
                for c, x in enumerate(g["xs"]):
                    slot = r * cols + c
                    if fr is not None:
                        f, rx, ry = fr
                        thumb = to_pixmap(f[y - ry:y - ry + g["h"], x - rx:x - rx + g["w"]])
                    else:
                        thumb = QPixmap()
                    cell = SlotCell(rid, slot, thumb, existing.get((rid, slot)))
                    self.cells.append(cell); grid.addWidget(cell, r, c)
        if not prof.regions.skill:
            v.addWidget(QLabel("스킬창 영역이 없습니다. 홈 → [스킬창 영역 추가] 로 먼저 지정하세요."))
        v.addStretch()

        foot = QWidget(); foot.setObjectName("footer"); fl = QHBoxLayout(foot); fl.setContentsMargins(28, 12, 28, 12); fl.addStretch()
        cancel = QPushButton("취소"); cancel.clicked.connect(self.close); fl.addWidget(cancel)
        save = QPushButton("저장"); save.setObjectName("primary"); save.clicked.connect(self._save); fl.addWidget(save)
        root.addWidget(foot)

    def _remove(self, rid):
        self.prof.regions.skill = [r for r in self.prof.regions.skill if r["id"] != rid]
        self.prof.skill_items = [it for it in self.prof.skill_items if it.region != rid]
        self.cfg.save(); self.close()
        if self.app:
            self.app.open_skills()

    def _redo(self, rid):
        """같은 id 로 영역을 다시 잡는다 (표시 설정은 슬롯 번호 기준으로 유지)"""
        self.close()
        self.app.calibrate("skill", redo_id=rid)

    def _save(self):
        self.prof.skill_items = [it for c in self.cells if (it := c.item())]
        self.cfg.save(); self.close()
        if self.on_saved:
            self.on_saved()