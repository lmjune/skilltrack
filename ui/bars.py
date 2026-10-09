"""
자원 알림 설정 창 (캐릭터별): 생명력 / 마나 / 스태미나마다
  켜기 · 기준 % · 글씨(자원 알림 칸) · 화면 효과(가장자리) · 소리, 마나는 '마나실드 켜져 있을 때만 화면 효과'.
글씨와 화면 효과는 따로 체크 → 둘 다 / 하나만 / 둘 다 끔.
"""
from dataclasses import replace

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox, QPushButton,
                               QFrame, QComboBox, QLineEdit)

from core.bars import NAMES, RELEASE, default_msg
from core.paths import APP_NAME


def muted(t):
    l = QLabel(t); l.setObjectName("muted"); l.setWordWrap(True); return l


class _Row(QFrame):
    def __init__(self, key, cfg):
        super().__init__()
        self.key = key
        self.setObjectName("card")
        v = QVBoxLayout(self); v.setContentsMargins(16, 10, 16, 10); v.setSpacing(6)
        top = QHBoxLayout(); top.setSpacing(8)
        self.on = QCheckBox(NAMES[key]); self.on.setChecked(cfg.enabled); self.on.setStyleSheet("font-weight:700;"); self.on.setFixedWidth(116)
        top.addWidget(self.on)
        self.pct = QSpinBox(); self.pct.setRange(1, 95); self.pct.setSuffix("%"); self.pct.setFixedWidth(76); self.pct.setValue(cfg.pct)
        top.addWidget(self.pct); top.addWidget(QLabel("이하일 때"))
        self.text = QCheckBox("글씨"); self.text.setChecked(cfg.text); self.text.setToolTip("자원 알림 칸에 '마나 20%' (회복하면 사라짐)")
        self.edge = QCheckBox("화면 효과"); self.edge.setChecked(cfg.edge); self.edge.setToolTip("화면 가장자리가 자원 색으로 물듦. 기준의 절반 이하면 진하게")
        top.addWidget(self.text); top.addWidget(self.edge)
        self.sound = QComboBox(); self.sound.setFixedWidth(100)
        for k, t in (("voice", "음성"), ("effect", "효과음"), ("none", "소리 없음")):
            self.sound.addItem(t, k)
        self.sound.setCurrentIndex(max(0, self.sound.findData(cfg.sound)))
        top.addWidget(self.sound); top.addStretch()
        v.addLayout(top)
        mr = QHBoxLayout(); mr.setSpacing(8)
        ml = QLabel("알림 문구"); ml.setFixedWidth(116); mr.addWidget(ml)
        self.msg = QLineEdit(cfg.msg); self.msg.setPlaceholderText(default_msg(key))
        self.msg.setToolTip("음성은 이 문구 그대로, 글씨 칸엔 '문구 22%'. 비우면 기본값")
        mr.addWidget(self.msg, 1); v.addLayout(mr)
        self.shield = None
        if key == "mp":
            self.shield = QCheckBox("마나실드가 켜져 있을 때만 화면 효과 (꺼져 있으면 글씨만)")
            self.shield.setChecked(cfg.shield_only)
            self.shield.setToolTip("상태창 [감시 항목]에 마나실드가 있을 때 동작. 없으면 항상 화면 효과")
            v.addWidget(self.shield)
        self.on.toggled.connect(self._enable); self._enable()

    def _enable(self, *_):
        on = self.on.isChecked()
        for w in (self.pct, self.text, self.edge, self.sound, self.shield, self.msg):
            if w is not None:
                w.setEnabled(on)

    def cfg(self, old):
        return replace(old, enabled=self.on.isChecked(), pct=self.pct.value(), text=self.text.isChecked(),
                       edge=self.edge.isChecked(), sound=self.sound.currentData() or "none", msg=self.msg.text().strip(),
                       shield_only=self.shield.isChecked() if self.shield is not None else old.shield_only)


class BarsWindow(QWidget):
    def __init__(self, app, prof):
        super().__init__()
        self.app, self.prof = app, prof
        self.setWindowTitle(APP_NAME); self.resize(620, 640)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        body = QWidget(); v = QVBoxLayout(body); v.setContentsMargins(28, 24, 28, 16); v.setSpacing(10)
        t = QLabel(f"자원 알림 — {prof.name}"); t.setObjectName("title"); v.addWidget(t)
        v.addWidget(muted("화면 아래 막대의 색으로 남은 비율을 잽니다 (숫자를 읽지 않아 글꼴·해상도와 무관). "
                          f"기준 아래로 1초 이상 머물면 알리고 (화면 전환 순간은 무시), 기준보다 {RELEASE}% 위로 회복하면 해제됩니다. "
                          "글씨는 별도의 '자원 알림' 칸에 뜨고 위치는 [배치 편집]에서 옮깁니다."))
        self.rows = [_Row(k, prof.bars[k]) for k in ("hp", "mp", "sp")]
        for r in self.rows:
            v.addWidget(r)
        v.addWidget(muted("음성은 알림 문구 그대로 (기본 \"생명력 부족\") — 생명력은 다른 소리를 끊고 가장 먼저 나옵니다 (일반 설정의 소리 켜기 필요)."))

        sec = QLabel("샘플 수집"); sec.setObjectName("section"); v.addWidget(sec)
        self.collect = QCheckBox("막대 숫자가 바뀔 때마다 실제 화면 저장 (색이 바뀌는 상태 확인용)")
        self.collect.setChecked(prof.bars_collect)
        fo = QPushButton("폴더 열기"); fo.setObjectName("ghost"); fo.clicked.connect(app.open_bars_folder)
        h = QHBoxLayout(); h.addWidget(self.collect); h.addWidget(fo); h.addStretch(); v.addLayout(h)
        v.addStretch()
        root.addWidget(body, 1)

        foot = QWidget(); foot.setObjectName("footer"); fl = QHBoxLayout(foot); fl.setContentsMargins(28, 12, 28, 12); fl.addStretch()
        cancel = QPushButton("취소"); cancel.clicked.connect(self.close); fl.addWidget(cancel)
        save = QPushButton("저장"); save.setObjectName("primary"); save.clicked.connect(self._save); fl.addWidget(save)
        root.addWidget(foot)

    def _save(self):
        p = self.prof
        for r in self.rows:
            p.bars[r.key] = r.cfg(p.bars[r.key])
        p.bars_collect = self.collect.isChecked()
        self.app.cfg.save()
        self.close()
        self.app._bars_saved()
