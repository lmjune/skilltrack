"""일반 설정 창: 단축키, 캡처 fps, 소리, 진단 저장, 게임 창 제목."""
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QSpinBox, QPushButton,
                               QFrame, QFileDialog, QMessageBox, QComboBox, QSlider, QScrollArea)

from core.config import Config
from core.screen import SCREENS, DEFAULT
from core.paths import APP_NAME


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


def _wrap(layout):
    w = QWidget(); layout.setContentsMargins(0, 0, 0, 0); w.setLayout(layout); return w


def field(label, w, hint=""):
    row = QHBoxLayout(); row.setSpacing(12)
    l = QLabel(label); l.setFixedWidth(150); row.addWidget(l); row.addWidget(w, 1)
    if hint:
        h = QLabel(hint); h.setObjectName("muted"); row.addWidget(h)
    return row


class GeneralWindow(QWidget):
    def __init__(self, cfg: Config, on_saved=None, player=None):
        super().__init__()
        self.cfg, self.on_saved, self.player = cfg, on_saved, player
        self._saved = False
        self.setWindowTitle(APP_NAME); self.resize(680, 760)
        g = cfg.general
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        head = QWidget(); hv = QVBoxLayout(head); hv.setContentsMargins(28, 24, 28, 12)
        t = QLabel("일반 설정"); t.setObjectName("title"); hv.addWidget(t); root.addWidget(head)

        body = QWidget(); v = QVBoxLayout(body); v.setContentsMargins(28, 8, 28, 16); v.setSpacing(10)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setWidget(body)
        root.addWidget(scroll, 1)

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
        self.ui_variant = QComboBox()
        for key, sc in SCREENS.items():
            self.ui_variant.addItem(sc.label, key)
        i = self.ui_variant.findData(g.ui_variant if g.ui_variant in SCREENS else DEFAULT)
        self.ui_variant.setCurrentIndex(max(0, i))
        l2.addLayout(field("UI 크기 변경", self.ui_variant, "게임 옵션과 같게"))
        uv_hint = QLabel("게임 옵션에서 UI 크기를 바꿨다면 여기서 같은 것을 고르세요 (150% 는 4K 만, 글씨체까지 맞게). "
                         "바꾸면 [영역 설정]을 다시 해야 합니다. 보스 디버프: 150% 는 마비옛체만 지원 (나눔고딕은 게임이 남은 시간의 'M'(분)을 안 그려 분·초를 구분할 수 없음)")
        uv_hint.setObjectName("muted"); uv_hint.setWordWrap(True); l2.addWidget(uv_hint)
        self.hdr = QComboBox()
        for key, lab in (("auto", "자동 감지 (권장)"), ("on", "HDR 켬"), ("off", "HDR 끔")):
            self.hdr.addItem(lab, key)
        self.hdr.setCurrentIndex(max(0, self.hdr.findData(getattr(g, "hdr_mode", "auto"))))
        l2.addLayout(field("윈도우 HDR", self.hdr, "UI 150%·배율 조정 100% 에서 글자 밝기 기준"))
        self.fps = QSpinBox(); self.fps.setRange(1, 30); self.fps.setValue(g.fps); self.fps.setFixedWidth(80)
        l2.addLayout(field("초당 확인 횟수", self.fps, "5면 충분. 높이면 CPU 사용 증가"))
        self.hide_inactive = QCheckBox("게임 창이 뒤로 가면 오버레이 숨김"); self.hide_inactive.setChecked(g.hide_when_inactive); l2.addWidget(self.hide_inactive)
        self.smooth = QCheckBox("스킬 아이콘 확대를 부드럽게 (끄면 픽셀 그대로, 각짐)"); self.smooth.setChecked(cfg.overlays.skill_smooth); l2.addWidget(self.smooth)
        self.diag = QCheckBox("문제 진단용 프레임 자동 저장 (diag 폴더)"); self.diag.setChecked(g.diag_save); l2.addWidget(self.diag)
        self.cap = QCheckBox("오버레이를 스크린샷에 포함 (가이드 작성용 — 평소엔 끄세요)"); self.cap.setChecked(g.capturable); l2.addWidget(self.cap)
        self.learn = QCheckBox("보스 디버프: 모르는 아이콘 자동 등록 (디버그용 — 평소엔 끄세요)"); self.learn.setChecked(g.boss_learn_icons); l2.addWidget(self.learn)
        v.addWidget(c2)

        s3 = QLabel("소리"); s3.setObjectName("section"); v.addWidget(s3)
        c3 = QFrame(); c3.setObjectName("card"); l3 = QVBoxLayout(c3); l3.setContentsMargins(16, 12, 16, 12); l3.setSpacing(8)
        self.sound_on = QCheckBox("소리 켜기"); self.sound_on.setChecked(g.sound); l3.addWidget(self.sound_on)
        vh = QLabel("끄면 모든 소리가 꺼집니다 (화면 알림은 그대로). "
                    "무엇을 어떤 소리로 알릴지는 항목마다 고릅니다 — 음성 / 효과음 / 소리 없음 (기본 소리 없음):\n"
                    "  · 상태창 버프: [감시 항목] 카드의 '소리'\n"
                    "  · 보스 디버프 빠짐·버스트: [보스 디버프] 줄의 소리 칸\n"
                    "아래는 소리의 목소리·크기만 정합니다.")
        vh.setObjectName("muted"); vh.setWordWrap(True); l3.addWidget(vh)

        self.voice_name = QComboBox()
        self.voice_name.addItem("자동 (한국어 목소리)", "")
        try:
            from win.voice import Tts
            for name, ko in Tts.list_voices():
                if ko:                                   # 한국어 아닌 목소리는 한글 문구를 못 읽음 → 목록에서 뺌
                    self.voice_name.addItem(name, name)
        except Exception:
            pass
        self.voice_name.setCurrentIndex(max(0, self.voice_name.findData(g.voice_name)))
        l3.addLayout(field("목소리", self.voice_name))

        def slider(val):
            sl = QSlider(Qt.Horizontal); sl.setRange(0, 100); sl.setValue(int(val)); sl.setSingleStep(5); sl.setPageStep(10)
            lab = QLabel(f"{int(val)}%"); lab.setFixedWidth(44)
            sl.valueChanged.connect(lambda x: lab.setText(f"{x}%"))
            row = QHBoxLayout(); row.addWidget(sl, 1); row.addWidget(lab)
            return sl, row
        self.voice_vol, r1 = slider(g.voice_volume); l3.addLayout(field("음성 볼륨", _wrap(r1)))
        self.effect_vol, r2 = slider(g.effect_volume); l3.addLayout(field("효과음 볼륨", _wrap(r2)))
        self.voice_rate = QSpinBox(); self.voice_rate.setRange(-5, 8); self.voice_rate.setValue(int(g.voice_rate)); self.voice_rate.setFixedWidth(80)
        l3.addLayout(field("말 빠르기", self.voice_rate, "0 = 보통, 높을수록 빠름"))
        self.sound_file = QLineEdit(g.sound_file); self.sound_file.setPlaceholderText("효과음 wav — 비우면 기본음 (심각도별)")
        pick = QPushButton("찾기"); pick.setObjectName("ghost"); pick.clicked.connect(self._pick_sound)
        fr = QHBoxLayout(); fr.addWidget(self.sound_file, 1); fr.addWidget(pick)
        l3.addLayout(field("효과음 파일", _wrap(fr)))
        t1 = QPushButton("음성 들어보기"); t1.clicked.connect(lambda: self._test("voice"))
        t2 = QPushButton("버스트 들어보기"); t2.clicked.connect(lambda: self._test("burst"))
        t3 = QPushButton("효과음 들어보기"); t3.clicked.connect(lambda: self._test("effect"))
        tr = QHBoxLayout(); tr.addWidget(t1); tr.addWidget(t2); tr.addWidget(t3); tr.addStretch(); l3.addLayout(tr)
        v.addWidget(c3)

        s4 = QLabel("가챠 덮개"); s4.setObjectName("section"); v.addWidget(s4)
        c4 = QFrame(); c4.setObjectName("card"); l4 = QVBoxLayout(c4); l4.setContentsMargins(16, 12, 16, 12); l4.setSpacing(8)
        self.gacha_image = QLineEdit(g.gacha_image); self.gacha_image.setPlaceholderText("비우면 어두운 단색")
        gp = QPushButton("찾기"); gp.setObjectName("ghost"); gp.clicked.connect(self._pick_gacha)
        gc = QPushButton("비우기"); gc.setObjectName("ghost"); gc.clicked.connect(lambda: self.gacha_image.setText(""))
        gr = QHBoxLayout(); gr.addWidget(self.gacha_image, 1); gr.addWidget(gp); gr.addWidget(gc)
        l4.addLayout(field("덮개 그림", _wrap(gr), "png·jpg. 창 크기에 꽉 차게 (넘치는 부분은 잘림)"))
        gh = QLabel("홈의 [가챠 덮개]로 켜고 끕니다. 끌어서 이동 · 가장자리로 크기 조절 · 휠을 내리면 위에서부터 줄어듭니다")
        gh.setObjectName("muted"); gh.setWordWrap(True); l4.addWidget(gh)
        v.addWidget(c4)
        v.addStretch()

        foot = QWidget(); foot.setObjectName("footer"); fl = QHBoxLayout(foot); fl.setContentsMargins(28, 12, 28, 12); fl.addStretch()
        cancel = QPushButton("취소"); cancel.clicked.connect(self.close); fl.addWidget(cancel)
        save = QPushButton("저장"); save.setObjectName("primary"); save.clicked.connect(self._save); fl.addWidget(save)
        root.addWidget(foot)

    def _pick_gacha(self):
        f, _ = QFileDialog.getOpenFileName(self, "가챠 덮개 그림", "", "그림 (*.png *.jpg *.jpeg *.bmp)")
        if f:
            self.gacha_image.setText(f)

    def _pick_sound(self):
        f, _ = QFileDialog.getOpenFileName(self, "효과음", "", "WAV (*.wav)")
        if f:
            self.sound_file.setText(f)

    def _apply_player(self, from_widgets=True):
        if not self.player:
            return
        if from_widgets:
            self.player.set_options(True, self.voice_vol.value(), self.effect_vol.value(),
                                    self.voice_rate.value(), self.voice_name.currentData() or "", self.sound_file.text().strip())
        else:
            g = self.cfg.general
            self.player.set_options(True, g.voice_volume, g.effect_volume, g.voice_rate, g.voice_name, g.sound_file)

    def _test(self, what):
        """저장 전 값으로 바로 들어보기 (닫을 때 저장 안 했으면 원래 값으로 되돌림)."""
        if not self.player:
            QMessageBox.information(self, APP_NAME, "소리 재생기를 시작하지 못했습니다 (로그 확인)"); return
        import time
        from core.speech import Utterance, P_BURST, P_OFF
        self._apply_player(True)
        if what == "burst":
            self.player.say(Utterance("voice", "붕파 적용!", "danger", P_BURST, time.time(), key=f"test{time.time()}"))
        elif what == "voice":
            self.player.say(Utterance("voice", "마나실드 꺼짐", "danger", P_OFF, time.time(), key=f"test{time.time()}"))
        else:
            self.player.say(Utterance("effect", level="danger", prio=P_OFF, at=time.time(), key=f"test{time.time()}"))

    def closeEvent(self, e):
        if not self._saved:
            self._apply_player(False)
        super().closeEvent(e)

    def _save(self):
        g = self.cfg.general
        g.sound = self.sound_on.isChecked()
        g.voice_volume, g.effect_volume = self.voice_vol.value(), self.effect_vol.value()
        g.voice_rate, g.voice_name = self.voice_rate.value(), self.voice_name.currentData() or ""
        g.sound_file = self.sound_file.text().strip()
        g.gacha_image = self.gacha_image.text().strip()
        self._saved = True
        g.hotkeys_enabled = self.hk_on.isChecked()
        g.hotkey_toggle, g.hotkey_settings, g.hotkey_edit = self.hk_toggle.text(), self.hk_settings.text(), self.hk_edit.text()
        g.window_title, g.fps = self.title.text().strip() or g.window_title, self.fps.value()
        g.hide_when_inactive, g.diag_save, g.capturable = self.hide_inactive.isChecked(), self.diag.isChecked(), self.cap.isChecked()
        g.boss_learn_icons = self.learn.isChecked()
        g.ui_variant = self.ui_variant.currentData() or DEFAULT
        g.hdr_mode = self.hdr.currentData() or "auto"
        self.cfg.overlays.skill_smooth = self.smooth.isChecked()
        self.cfg.save()
        if self.on_saved:
            self.on_saved()
        self.close()