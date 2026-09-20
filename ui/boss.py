"""
보스 디버프 설정 창. 등록된 아이콘(assets/boss_icons) 전부를 크게 보여주고
  - 이름 (공용, icons.json)           ← 같은 이름이면 한 항목으로 묶임 (스택 변형 등)
  - 감시 (이 캐릭터, profile.boss_watches)  빠지면 오버레이에 표시
  - 재표시 임계 "60,40,20"             남은 초가 이 이하로 내려갈 때 다시 표시
  - 버스트 + 문구                      걸리는 순간 알림 토스트
저장하면 icons.json + config.json.
"""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QCheckBox, QLineEdit, QPushButton,
                               QScrollArea, QFrame)

from core.bossbar import IconLib
from core.config import Config, BossWatchCfg
from core.paths import APP_NAME

THUMB = 4


def to_pixmap(bgr, scale=THUMB):
    bgr = np.ascontiguousarray(bgr)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
    return QPixmap.fromImage(qi).scaled(rgb.shape[1] * scale, rgb.shape[0] * scale, Qt.KeepAspectRatio, Qt.FastTransformation)


def parse_thresholds(text) -> list:
    out = []
    for t in text.replace(" ", "").split(","):
        if t.isdigit() and int(t) > 0:
            out.append(int(t))
    return sorted(set(out), reverse=True)


class IconRow(QFrame):
    """아이콘 하나(또는 같은 이름으로 묶인 여러 개)의 한 줄."""

    def __init__(self, ids, icons: IconLib, cfg: BossWatchCfg | None, unnamed=False):
        super().__init__()
        self.ids, self.icons = ids, icons
        self.setObjectName("card")
        h = QHBoxLayout(self); h.setContentsMargins(12, 8, 12, 8); h.setSpacing(12)
        pics = QHBoxLayout(); pics.setSpacing(2)
        for k in ids:
            pic = QLabel(); pic.setPixmap(to_pixmap(icons.items[k])); pic.setToolTip(k); pics.addWidget(pic)
        h.addLayout(pics)
        self.name = QLineEdit(icons.meta.get(ids[0], {}).get("name", "")); self.name.setPlaceholderText("이름 (같은 이름 = 한 항목)")
        self.name.setFixedWidth(150); h.addWidget(self.name)
        self.stack = QCheckBox("스택형"); self.stack.setObjectName("small"); self.stack.setToolTip("숫자만 바뀌는 변형(1~5 스택)을 같은 아이콘으로 봄")
        self.stack.setChecked(any("stack" in icons.meta.get(k, {}).get("tags", []) for k in ids)); h.addWidget(self.stack)
        self.on = QCheckBox("감시"); self.on.setChecked(cfg is not None and cfg.enabled)
        self.on.setToolTip("빠지면 목록에 표시. 버스트 알림만 원하면 끄고 버스트만 켜세요"); h.addWidget(self.on)
        h.addWidget(QLabel("재표시(초)"))
        self.th = QLineEdit(",".join(str(t) for t in (cfg.thresholds if cfg else [60, 40, 20]))); self.th.setFixedWidth(90)
        self.th.setToolTip("남은 초가 이 이하로 내려가면 목록에 다시 표시. 비우면 빠졌을 때만 표시 (지속 10초짜리 버스트는 비우세요)"); h.addWidget(self.th)
        self.burst = QCheckBox("버스트"); self.burst.setChecked(bool(cfg and cfg.burst)); h.addWidget(self.burst)
        self.burst_text = QLineEdit(cfg.burst_text if cfg else ""); self.burst_text.setPlaceholderText("알림 문구 (비우면 '이름 적용!')")
        self.burst_text.setFixedWidth(180); h.addWidget(self.burst_text)
        h.addStretch()
        if unnamed:
            hint = QLabel("이름을 붙이면 감시할 수 있음"); hint.setObjectName("muted"); h.addWidget(hint)
        for w in (self.on, self.th, self.burst, self.burst_text):
            w.setEnabled(bool(self.name.text().strip()))
        self.name.textChanged.connect(lambda t: [w.setEnabled(bool(t.strip())) for w in (self.on, self.th, self.burst, self.burst_text)])

    def apply(self, watches: dict):
        name = self.name.text().strip()
        tags = ["stack"] if self.stack.isChecked() else []
        for k in self.ids:
            self.icons.meta[k] = {"name": name, "tags": tags}
        if name and (self.on.isChecked() or self.burst.isChecked()):
            watches[name] = BossWatchCfg(enabled=self.on.isChecked(), thresholds=parse_thresholds(self.th.text()),
                                         burst=self.burst.isChecked(), burst_text=self.burst_text.text().strip())


class BossWindow(QWidget):
    def __init__(self, cfg: Config, prof, icons: IconLib, on_saved=None):
        super().__init__()
        self.cfg, self.prof, self.icons, self.on_saved = cfg, prof, icons, on_saved
        self.setWindowTitle(APP_NAME); self.resize(1080, 720)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        head = QWidget(); hv = QVBoxLayout(head); hv.setContentsMargins(28, 24, 28, 12); hv.setSpacing(4)
        t = QLabel(f"보스 디버프 — {prof.name}"); t.setObjectName("title"); hv.addWidget(t)
        s = QLabel("보스 체력바 위 디버프 띠를 읽어, 감시 항목 중 빠진 것을 화면에 띄웁니다 (띠가 있는 보스에서만). "
                   "감시 = 빠지면 목록에 표시 · 재표시 = 남은 초가 그 이하면 다시 표시 · 버스트 = 걸리는 순간 알림 (감시 없이 버스트만도 가능). "
                   "이름은 모든 캐릭터 공용, 나머지는 이 캐릭터 설정. 새 아이콘은 전투 중 자동 등록.")
        s.setObjectName("subtitle"); s.setWordWrap(True); hv.addWidget(s)
        self.enabled = QCheckBox("이 캐릭터에서 보스 디버프 감시 사용"); self.enabled.setChecked(prof.boss_enabled); hv.addWidget(self.enabled)
        root.addWidget(head)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); root.addWidget(scroll, 1)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(28, 8, 28, 16); v.setSpacing(8); scroll.setWidget(inner)
        self.rows = []
        groups, unnamed = {}, []
        for k in icons.items:
            n = icons.meta.get(k, {}).get("name", "")
            (groups.setdefault(n, []) if n else unnamed).append(k)
        if groups:
            sec = QLabel("이름 있는 아이콘"); sec.setObjectName("section"); v.addWidget(sec)
            for n, ids in sorted(groups.items()):
                r = IconRow(ids, icons, prof.boss_watches.get(n)); self.rows.append(r); v.addWidget(r)
        if unnamed:
            sec = QLabel("이름 없는 아이콘 (자동 등록됨)"); sec.setObjectName("section"); v.addWidget(sec)
            for k in unnamed:
                r = IconRow([k], icons, None, unnamed=True); self.rows.append(r); v.addWidget(r)
        if not icons.items:
            v.addWidget(QLabel("등록된 아이콘이 없습니다. 띠가 있는 보스와 싸우면 자동으로 모입니다."))
        v.addStretch()

        foot = QWidget(); foot.setObjectName("footer"); fh = QHBoxLayout(foot); fh.setContentsMargins(28, 12, 28, 12)
        fh.addWidget(QLabel("빠진 디버프 목록의 위치·크기는 [배치 편집]에서. 버스트 알림은 알림창에 뜹니다.")); fh.addStretch()
        b = QPushButton("저장"); b.setObjectName("primary"); b.clicked.connect(self.save); fh.addWidget(b)
        root.addWidget(foot)

    def save(self):
        watches = {}
        for r in self.rows:
            r.apply(watches)
        self.icons.save_meta()
        self.prof.boss_enabled = self.enabled.isChecked()
        self.prof.boss_watches = watches
        self.cfg.save()
        if self.on_saved:
            self.on_saved()
        self.close()