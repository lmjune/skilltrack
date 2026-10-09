"""
투아림 설정 창 (캐릭터별): 알림 켜기, 곧 투아림 %, 도르카 부족, 투아림 발동 알림, 소리, 샘플 수집.
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox, QPushButton,
                               QFrame, QComboBox)

from core.paths import APP_NAME
from core.tuarim import SECS_PER_PCT, _time


def muted(t):
    l = QLabel(t); l.setObjectName("muted"); l.setWordWrap(True); return l


def row(*ws, stretch=True):
    h = QHBoxLayout(); h.setSpacing(8)
    for w in ws:
        h.addWidget(w)
    if stretch:
        h.addStretch()
    return h


class TuarimWindow(QWidget):
    def __init__(self, app, prof):
        super().__init__()
        self.app, self.prof = app, prof
        self.setWindowTitle(APP_NAME); self.resize(560, 520)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        body = QWidget(); v = QVBoxLayout(body); v.setContentsMargins(28, 24, 28, 16); v.setSpacing(10)
        t = QLabel(f"투아림 — {prof.name}"); t.setObjectName("title"); v.addWidget(t)
        v.addWidget(muted("도르카 숫자와 부스트 %를 읽어 알려줍니다. 부스트는 전투 600초면 100% (1% = 6초) — "
                          "남은 시간은 전투가 이어진다는 가정의 예측입니다."))

        card = QFrame(); card.setObjectName("card"); c = QVBoxLayout(card); c.setContentsMargins(16, 12, 16, 12); c.setSpacing(10)
        self.enabled = QCheckBox("투아림 알림 사용"); self.enabled.setChecked(prof.tuarim_enabled); c.addWidget(self.enabled)

        self.soon_on = QCheckBox("곧 투아림")
        self.soon = QSpinBox(); self.soon.setRange(1, 99); self.soon.setSuffix("%"); self.soon.setFixedWidth(80)
        self.soon.setValue(prof.tuarim_soon_pct or 95); self.soon_on.setChecked(bool(prof.tuarim_soon_pct))
        self.soon_hint = muted("")
        self.soon.valueChanged.connect(self._hint); self._hint()
        c.addLayout(row(self.soon_on, QLabel("부스트가"), self.soon, QLabel("이상이면 한 번"), self.soon_hint))

        self.low_on = QCheckBox("도르카 부족")
        self.low = QSpinBox(); self.low.setRange(1, 14); self.low.setFixedWidth(70)
        self.low.setValue(prof.tuarim_dorca_low or 3); self.low_on.setChecked(bool(prof.tuarim_dorca_low))
        c.addLayout(row(self.low_on, QLabel("도르카가"), self.low, QLabel("이하로 떨어지면 한 번")))

        self.burst = QCheckBox("투아림 발동 알림 (\"투아림!\")"); self.burst.setChecked(prof.tuarim_burst); c.addWidget(self.burst)

        self.sound = QComboBox(); self.sound.setFixedWidth(110)
        for key, text in (("voice", "음성"), ("effect", "효과음"), ("none", "소리 없음")):
            self.sound.addItem(text, key)
        self.sound.setCurrentIndex(max(0, self.sound.findData(prof.tuarim_sound)))
        c.addLayout(row(QLabel("소리"), self.sound, muted("음성: \"투아림 30초 전\", \"도르카 부족\" (일반 설정의 소리 켜기 필요)")))
        v.addWidget(card)

        sec = QLabel("샘플 수집 (새 UI 크기 지원용)"); sec.setObjectName("section"); v.addWidget(sec)
        card2 = QFrame(); card2.setObjectName("card"); c2 = QVBoxLayout(card2); c2.setContentsMargins(16, 12, 16, 12); c2.setSpacing(8)
        self.collect = QCheckBox("숫자가 바뀔 때마다 실제 화면 저장"); self.collect.setChecked(prof.tuarim_collect)
        fo = QPushButton("폴더 열기"); fo.setObjectName("ghost"); fo.clicked.connect(app.open_tuarim_folder)
        c2.addLayout(row(self.collect, fo))
        c2.addWidget(muted("지원: UI 100%(모든 해상도), 4K UI 150% 마비옛체·나눔고딕. 다른 UI 크기에서 안 읽히면 켜서 모아 보내주세요."))
        v.addWidget(card2)
        v.addStretch()
        root.addWidget(body, 1)

        foot = QWidget(); foot.setObjectName("footer"); fl = QHBoxLayout(foot); fl.setContentsMargins(28, 12, 28, 12); fl.addStretch()
        cancel = QPushButton("취소"); cancel.clicked.connect(self.close); fl.addWidget(cancel)
        save = QPushButton("저장"); save.setObjectName("primary"); save.clicked.connect(self._save); fl.addWidget(save)
        root.addWidget(foot)

    def _hint(self):
        s = int(round((100 - self.soon.value()) * SECS_PER_PCT))
        self.soon_hint.setText(f"(투아림 약 {_time(s)} 전)")

    def _save(self):
        p = self.prof
        p.tuarim_enabled = self.enabled.isChecked()
        p.tuarim_soon_pct = self.soon.value() if self.soon_on.isChecked() else 0
        p.tuarim_dorca_low = self.low.value() if self.low_on.isChecked() else 0
        p.tuarim_burst = self.burst.isChecked()
        p.tuarim_sound = self.sound.currentData() or "none"
        p.tuarim_collect = self.collect.isChecked()
        self.app.cfg.save()
        self.close()
        self.app._tuarim_saved()
