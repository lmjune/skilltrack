"""일반 설정 창: 단축키, 캡처 fps, 소리, 진단 저장, 게임 창 제목."""
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QSpinBox, QPushButton,
                               QFrame, QFileDialog, QMessageBox)

from core.config import Config


class HotkeyEdit(QLineEdit):
    """칸을 클릭한 뒤 키 조합을 누르면 'Ctrl+Shift+F9' 형식으로 채워진다. Backspace = 비우기(끔)."""
    NAMES = {Qt.Key_F1 + i: f"F{i + 1}" for i in range(24)}

    def __init__(self, text=""):
        super().__init__(text)
        self.setPlaceholderText("클릭 후 키를 누르세요 (Backspace = 사용 안 함)")
        self.setReadOnly(True)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Backspace, Qt.Key_Delete):
            self.setText(""); return
        if k in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_unknown):
            return
        mods = []
        m = e.modifiers()
        if m & Qt.ControlModifier: mods.append("Ctrl")
        if m & Qt.AltModifier: mods.append("Alt")
        if m & Qt.ShiftModifier: mods.append("Shift")
        if k in self.NAMES:
            name = self.NAMES[k]
        else:
            name = QKeySequence(k).toString()
            if not name or len(name) > 12:
                return
        self.setText("+".join(mods + [name]))


def field(label, w, hint=""):
    row = QHBoxLayout(); row.setSpacing(12)
    l = QLabel(label); l.setFixedWidth(150); row.addWidget(l); row.addWidget(w, 1)
    if hint:
        h = QLabel(hint); h.setObjectName("muted"); row.addWidget(h)
    return row


class GeneralWindow(QWidget):
    def __init__(self, cfg: Config, on_saved=None):
        super().__init__()
        self.cfg, self.on_saved = cfg, on_saved
        self.setWindowTitle("skilltrack"); self.resize(640, 520)
        g = cfg.general
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        head = QWidget(); hv = QVBoxLayout(head); hv.setContentsMargins(28, 24, 28, 12)
        t = QLabel("일반 설정"); t.setObjectName("title"); hv.addWidget(t); root.addWidget(head)

        body = QWidget(); v = QVBoxLayout(body); v.setContentsMargins(28, 8, 28, 16); v.setSpacing(10); root.addWidget(body, 1)

        s1 = QLabel("단축키"); s1.setObjectName("section"); v.addWidget(s1)
        c1 = QFrame(); c1.setObjectName("card"); l1 = QVBoxLayout(c1); l1.setContentsMargins(16, 12, 16, 12); l1.setSpacing(8)
        self.hk_on = QCheckBox("단축키 사용"); self.hk_on.setChecked(g.hotkeys_enabled); l1.addWidget(self.hk_on)
        hint = QLabel("키를 가로채지 않아 게임에도 같이 들어갑니다. 게임에서 안 쓰는 키(F9~F12, Ctrl 조합)를 고르세요. 기본은 꺼짐 — 트레이 아이콘 클릭으로 켜고 끕니다")
        hint.setObjectName("muted"); hint.setWordWrap(True); l1.addWidget(hint)
        self.hk_toggle = HotkeyEdit(g.hotkey_toggle); l1.addLayout(field("켜기/끄기", self.hk_toggle, "감시·알림·오버레이 전체"))
        self.hk_settings = HotkeyEdit(g.hotkey_settings); l1.addLayout(field("홈 화면 열기", self.hk_settings))
        self.hk_edit = HotkeyEdit(g.hotkey_edit); l1.addLayout(field("배치 편집", self.hk_edit))
        v.addWidget(c1)

        s2 = QLabel("동작"); s2.setObjectName("section"); v.addWidget(s2)
        c2 = QFrame(); c2.setObjectName("card"); l2 = QVBoxLayout(c2); l2.setContentsMargins(16, 12, 16, 12); l2.setSpacing(8)
        self.title = QLineEdit(g.window_title); l2.addLayout(field("게임 창 제목", self.title, "작업 표시줄에 보이는 이름"))
        self.fps = QSpinBox(); self.fps.setRange(1, 30); self.fps.setValue(g.fps); self.fps.setFixedWidth(80)
        l2.addLayout(field("초당 확인 횟수", self.fps, "5면 충분. 높이면 CPU 사용 증가"))
        self.hide_inactive = QCheckBox("게임 창이 뒤로 가면 오버레이 숨김"); self.hide_inactive.setChecked(g.hide_when_inactive); l2.addWidget(self.hide_inactive)
        self.smooth = QCheckBox("스킬 아이콘 확대를 부드럽게 (끄면 픽셀 그대로, 각짐)"); self.smooth.setChecked(cfg.overlays.skill_smooth); l2.addWidget(self.smooth)
        self.diag = QCheckBox("문제 진단용 프레임 자동 저장 (tests/fixtures/auto)"); self.diag.setChecked(g.diag_save); l2.addWidget(self.diag)
        self.cap = QCheckBox("오버레이를 스크린샷에 포함 (가이드 작성용 — 평소엔 끄세요)"); self.cap.setChecked(g.capturable); l2.addWidget(self.cap)
        v.addWidget(c2)
        v.addStretch()

        foot = QWidget(); foot.setObjectName("footer"); fl = QHBoxLayout(foot); fl.setContentsMargins(28, 12, 28, 12); fl.addStretch()
        cancel = QPushButton("취소"); cancel.clicked.connect(self.close); fl.addWidget(cancel)
        save = QPushButton("저장"); save.setObjectName("primary"); save.clicked.connect(self._save); fl.addWidget(save)
        root.addWidget(foot)

    def _save(self):
        g = self.cfg.general
        g.hotkeys_enabled = self.hk_on.isChecked()
        g.hotkey_toggle, g.hotkey_settings, g.hotkey_edit = self.hk_toggle.text(), self.hk_settings.text(), self.hk_edit.text()
        g.window_title, g.fps = self.title.text().strip() or g.window_title, self.fps.value()
        g.hide_when_inactive, g.diag_save, g.capturable = self.hide_inactive.isChecked(), self.diag.isChecked(), self.cap.isChecked()
        self.cfg.overlays.skill_smooth = self.smooth.isChecked()
        self.cfg.save()
        if self.on_saved:
            self.on_saved()
        self.close()