"""
감시 항목 설정 창. 카드 목록: [썸네일] 이름  ····  감시 토글  [설정]. 설정을 누르면 그 카드가 펼쳐진다.
저장하면 profiles/config.json. 게임이 켜져 있어야 썸네일을 캡처한다.

사용법: python ui/watches.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QLineEdit,
                               QSpinBox, QPushButton, QScrollArea, QFrame, QFileDialog, QMessageBox)

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import Config, WatchCfg, MirrorRow
from core.paths import APP_NAME
from core.status import parse_rows
from core import variants
from ui import theme


def to_pixmap(bgr, scale=2):
    bgr = np.ascontiguousarray(bgr)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
    return QPixmap.fromImage(qi).scaled(rgb.shape[1] * scale, rgb.shape[0] * scale, Qt.KeepAspectRatio, Qt.FastTransformation)


def ints(text):
    return [int(t) for t in text.replace(" ", "").split(",") if t.strip().isdigit()]


def hbox(*widgets, stretch_end=True, spacing=10):
    l = QHBoxLayout(); l.setSpacing(spacing); l.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        l.addWidget(w)
    if stretch_end:
        l.addStretch()
    return l


def muted(text):
    l = QLabel(text); l.setObjectName("muted"); return l


class RowCard(QFrame):
    def __init__(self, row, thumb, w: WatchCfg, m: MirrorRow | None, pid=None):
        super().__init__()
        self.row, self.pid = row, pid
        self.var_checks = []
        self.setObjectName("card")
        v = QVBoxLayout(self); v.setContentsMargins(16, 12, 16, 12); v.setSpacing(8)

        # --- 요약 줄 ---
        pic = QLabel(); pic.setObjectName("thumb"); pic.setPixmap(thumb)
        self.label = QLineEdit(w.label); self.label.setObjectName("ghost"); self.label.setPlaceholderText(f"행 {row}  (이름 입력 — 선택)")
        self.enabled = QCheckBox("감시"); self.enabled.setChecked(w.enabled)
        self.btn = QPushButton("설정"); self.btn.setObjectName("ghost"); self.btn.setCheckable(True)
        head = QHBoxLayout(); head.setSpacing(14)
        head.addWidget(pic); head.addWidget(self.label, 1); head.addWidget(self.enabled); head.addWidget(self.btn)
        v.addLayout(head)

        # --- 상세 ---
        self.detail = QWidget(); d = QVBoxLayout(self.detail); d.setContentsMargins(0, 6, 0, 0); d.setSpacing(6)
        line = QFrame(); line.setObjectName("divider"); d.addWidget(line)

        self.alert_off = QCheckBox("꺼지는 순간 알림"); self.alert_off.setChecked(w.alert_off); d.addWidget(self.alert_off)

        self.keep = QCheckBox("켜질 때까지 반복 알림"); self.keep.setChecked(w.keep)
        self.keep_delay = QSpinBox(); self.keep_delay.setRange(0, 600); self.keep_delay.setValue(int(w.keep_delay)); self.keep_delay.setSuffix("초"); self.keep_delay.setFixedWidth(72)
        self.keep_interval = QSpinBox(); self.keep_interval.setRange(5, 3600); self.keep_interval.setValue(int(w.keep_interval)); self.keep_interval.setSuffix("초"); self.keep_interval.setFixedWidth(72)
        d.addLayout(hbox(self.keep, muted("꺼진 지"), self.keep_delay, muted("뒤부터"), self.keep_interval, muted("마다")))
        d.addWidget(muted("      마나실드·엘레멘탈 부여처럼 꺼진 채로 두면 안 되는 버프에 씁니다"))

        self.under_on = QCheckBox("남은 시간 알림"); self.under_on.setChecked(bool(w.alert_under))
        self.under = QLineEdit(",".join(map(str, w.alert_under)) or "60,30"); self.under.setFixedWidth(80)
        self.under_ext = QLineEdit(",".join(map(str, w.alert_under_extended)) or "120,60"); self.under_ext.setFixedWidth(80)
        d.addLayout(hbox(self.under_on, self.under, muted("초 미만일 때"), muted("·  연장 중이면"), self.under_ext, muted("초  (쉼표로 여러 개)")))

        self.mirror = QCheckBox("화면에 크게 표시"); self.mirror.setChecked(m is not None)
        self.m_icon = QCheckBox("아이콘"); self.m_name = QCheckBox("이름"); self.m_time = QCheckBox("시간"); self.m_only = QCheckBox("활성일 때만")
        for c, val in ((self.m_icon, m.icon if m else True), (self.m_name, m.name if m else True),
                       (self.m_time, m.time if m else True), (self.m_only, m.only_active if m else False)):
            c.setObjectName("small"); c.setChecked(val)
        d.addLayout(hbox(self.mirror, self.m_icon, self.m_name, self.m_time, self.m_only, spacing=16))

        self.alert_on = QCheckBox("켜지는 순간도 알림"); self.alert_on.setChecked(w.alert_on); self.alert_on.setObjectName("small")
        d.addLayout(hbox(self.alert_on, muted("보통은 필요 없음")))

        # 이름 접미어 변형: 자동 저장된 것들 중 '연장으로 취급' 선택
        vs = variants.load(pid, None) if pid else []
        if vs:
            d.addWidget(muted("이름 뒤에 붙는 글자 (자동 수집, 모든 버프 공통). 시간이 늘어나는 연장이면 체크 → 연장 임계값 사용"))
            for vinfo in vs:
                png = variants._folder(pid) / f"{vinfo['key']}.png"
                pic = QLabel(); pic.setObjectName("thumb")
                if png.exists():
                    import cv2 as _cv
                    img = _cv.imread(str(png))
                    if img is not None:
                        pic.setPixmap(to_pixmap(img, 2))
                cb = QCheckBox("연장으로 취급"); cb.setObjectName("small"); cb.setChecked(vinfo["extends"])
                lb = QLineEdit(vinfo["label"]); lb.setPlaceholderText("메모 (예: 투안의 노래)"); lb.setFixedWidth(160)
                self.var_checks.append((vinfo["key"], cb, lb))
                d.addLayout(hbox(pic, cb, lb, spacing=12))
        v.addWidget(self.detail)

        self.btn.toggled.connect(self._toggle); self.enabled.toggled.connect(self._toggle)
        self.detail.setVisible(False); self._toggle()

    def _toggle(self):
        on = self.enabled.isChecked()
        self.btn.setEnabled(on)
        self.detail.setVisible(on and self.btn.isChecked())

    def watch_cfg(self) -> WatchCfg:
        return WatchCfg(label=self.label.text().strip(), enabled=self.enabled.isChecked(),
                        alert_off=self.alert_off.isChecked(), alert_on=self.alert_on.isChecked(),
                        alert_under=ints(self.under.text()) if self.under_on.isChecked() else [],
                        alert_under_extended=ints(self.under_ext.text()) if self.under_on.isChecked() else [],
                        keep=self.keep.isChecked(), keep_delay=self.keep_delay.value(), keep_interval=self.keep_interval.value())

    def mirror_cfg(self) -> MirrorRow | None:
        if not (self.enabled.isChecked() and self.mirror.isChecked()):
            return None
        return MirrorRow(row=self.row, icon=self.m_icon.isChecked(), name=self.m_name.isChecked(),
                         time=self.m_time.isChecked(), only_active=self.m_only.isChecked(), dim_inactive=True)


class WatchesWindow(QWidget):
    def __init__(self, cfg: Config, prof, layout, frame, on_saved=None):
        super().__init__()
        self.cfg, self.prof, self.on_saved = cfg, prof, on_saved
        self.setWindowTitle(APP_NAME)
        self.resize(820, 780)
        states = {s.index: s for s in parse_rows(frame, layout)}
        mirrors = {m.row: m for m in prof.mirror_rows}

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        head = QWidget(); hv = QVBoxLayout(head); hv.setContentsMargins(28, 24, 28, 12); hv.setSpacing(4)
        t = QLabel(f"감시 항목 — {prof.name}"); t.setObjectName("title"); hv.addWidget(t)
        s = QLabel("게임에서 고정(핀)한 버프 목록입니다. 감시할 것을 켜고, 필요하면 설정에서 알림 방식을 바꾸세요."); s.setObjectName("subtitle"); hv.addWidget(s)
        root.addWidget(head)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); root.addWidget(scroll, 1)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(28, 8, 28, 16); v.setSpacing(10); scroll.setWidget(inner)
        self.cards = []
        for i, rw in enumerate(layout.rows):
            ix, iy, iw, ih = rw.icon; tx, ty, tw, th = rw.text
            st = states.get(i)
            a, b = (st.name_range if st and st.name_range else (0, min(tw, 140)))
            thumb = np.concatenate([frame[iy:iy + ih, ix:ix + iw], np.zeros((ih, 4, 3), np.uint8),
                                    frame[ty:ty + th, tx + a:tx + b + 1][:ih]], axis=1)
            card = RowCard(i, to_pixmap(thumb), prof.watches.get(i, WatchCfg(enabled=False)), mirrors.get(i), pid=cfg.current)
            self.cards.append(card); v.addWidget(card)

        sec = QLabel("공통"); sec.setObjectName("section"); v.addSpacing(8); v.addWidget(sec)
        common = QFrame(); common.setObjectName("card"); cl = QVBoxLayout(common); cl.setContentsMargins(16, 12, 16, 12)
        self.sound_on = QCheckBox("알림 소리"); self.sound_on.setChecked(cfg.general.sound)
        self.sound = QLineEdit(cfg.general.sound_file); self.sound.setPlaceholderText("wav 파일 — 비우면 기본 알림음 (심각도별)")
        pick = QPushButton("찾기"); pick.clicked.connect(self._pick_sound)
        cl.addLayout(hbox(self.sound_on, self.sound, pick, stretch_end=False))

        v.addWidget(common); v.addStretch()

        foot = QWidget(); foot.setObjectName("footer"); fl = QHBoxLayout(foot); fl.setContentsMargins(28, 12, 28, 12)
        fl.addWidget(muted("저장하면 profiles/config.json 에 기록됩니다")); fl.addStretch()
        cancel = QPushButton("취소"); cancel.clicked.connect(self.close); fl.addWidget(cancel)
        save = QPushButton("저장"); save.setObjectName("primary"); save.clicked.connect(self._save); fl.addWidget(save)
        root.addWidget(foot)

    def _pick_sound(self):
        f, _ = QFileDialog.getOpenFileName(self, "알림 소리", "", "WAV (*.wav)")
        if f:
            self.sound.setText(f)

    def _save(self):
        prof = self.prof
        for c in self.cards:
            for key, cb, lb in c.var_checks:
                variants.set_flags(self.cfg.current, c.row, key, label=lb.text().strip(), extends=cb.isChecked())
        prof.watches = {c.row: c.watch_cfg() for c in self.cards if c.enabled.isChecked()}
        prof.mirror_rows = [m for c in self.cards if (m := c.mirror_cfg())]
        self.cfg.general.sound_file = self.sound.text().strip()
        self.cfg.general.sound = self.sound_on.isChecked()
        self.cfg.save()
        self.close()
        if self.on_saved:
            self.on_saved()


def main():
    print("이 창은 트레이 앱(python win/run.py) 안에서 엽니다: 트레이 아이콘 → 감시 항목…")


if __name__ == "__main__":
    main()