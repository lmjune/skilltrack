"""
홈: 캐릭터(프로필) 목록. 추가 / 선택 / 이름 변경 / 삭제, 그리고 각 캐릭터의 설정 단계 버튼.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QInputDialog,
                               QMessageBox, QScrollArea, QCheckBox)

from core import layout_store
from core.paths import VERSION, APP_NAME


def muted(t):
    l = QLabel(t); l.setObjectName("muted"); return l


class ProfileCard(QFrame):
    def __init__(self, home, pid, prof, current, sess_rows, n_watch):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self); v.setContentsMargins(16, 12, 16, 12); v.setSpacing(8)

        head = QHBoxLayout(); head.setSpacing(10)
        name = QLabel(prof.name); name.setStyleSheet("font-size:16px; font-weight:700;")
        head.addWidget(name)
        if current:
            tag = QLabel("● 사용 중"); tag.setStyleSheet("color:#5b8cff; font-weight:600;"); head.addWidget(tag)
        head.addStretch()
        if not current:
            b = QPushButton("이 캐릭터로 전환"); b.clicked.connect(lambda: home.app.switch_profile(pid)); head.addWidget(b)
        rn = QPushButton("이름"); rn.setObjectName("ghost"); rn.clicked.connect(lambda: home.rename(pid)); head.addWidget(rn)
        rm = QPushButton("삭제"); rm.setObjectName("ghost"); rm.clicked.connect(lambda: home.remove(pid)); head.addWidget(rm)
        v.addLayout(head)

        has_region = bool(prof.regions.status)
        saved = layout_store.load(pid)
        has_layout = saved is not None
        partial = saved is not None and len(saved[3]) < len(saved[1].rows)   # 획 자리 빠진 행 있음
        st = QHBoxLayout(); st.setSpacing(18)
        st.addWidget(QLabel(("✓" if has_region else "✗") + " 상태창 영역"))
        st.addWidget(QLabel(("✓" if has_layout else "✗") + " 레이아웃" + (f" ({sess_rows}행)" if current and sess_rows else "")))
        st.addWidget(QLabel(f"감시 {n_watch}개" if n_watch else "감시 없음"))
        st.addWidget(QLabel(f"스킬창 {len(prof.regions.skill)}개 · 표시 {len(prof.skill_items)}개"))
        st.addWidget(QLabel(f"보스 디버프 {len(prof.boss_watches)}개" if prof.boss_enabled else "보스 디버프 끔"))
        st.addStretch(); v.addLayout(st)

        if not has_region:
            hint = "다음: [영역 설정] — 시간이 표시되는 버프 하나 켜고, 어두운 곳에서 상태창을 드래그"
        elif not has_layout:
            hint = "다음: 이 캐릭터로 전환하면 레이아웃을 자동으로 잡습니다 (어두운 곳에서)" if not current else "레이아웃을 잡는 중이거나 실패했습니다. 어두운 곳에서 [레이아웃 다시]"
        elif partial:
            hint = f"⚠ 밝은 곳에서 잡혀 일부 행({len(saved[1].rows) - len(saved[3])}개)을 판정 못 합니다. 어두운 곳에서 [레이아웃 다시]"
        elif current and home.app.mismatch and home.app.mismatch_warned:
            hint = "⚠ 저장된 항목과 지금 상태창이 다릅니다. 고정 목록을 바꿨으면 [레이아웃 다시], 다른 캐릭터면 그 캐릭터로 전환"
        elif not n_watch:
            hint = "다음: [감시 항목] 에서 감시할 버프를 켜세요"
        else:
            hint = "설정 완료"
        v.addWidget(muted(hint))

        # 기능별로 한 줄씩: 제목 + 버튼 (한 줄에 다 넣으면 창이 너무 가로로 길어진다)
        def group(title, *buttons):
            h = QHBoxLayout(); h.setSpacing(8)
            t = QLabel(title); t.setFixedWidth(52); t.setStyleSheet("font-weight:600;"); h.addWidget(t)
            for b in buttons:
                h.addWidget(b)
            h.addStretch(); v.addLayout(h)
        b1 = QPushButton("영역 설정"); b1.clicked.connect(lambda: home.app.calibrate("status", pid))
        b2 = QPushButton("감시 항목"); b2.setEnabled(current and has_layout); b2.clicked.connect(home.app.open_watches)
        b3 = QPushButton("레이아웃 다시"); b3.setEnabled(current and has_region); b3.clicked.connect(lambda: home.app.start_session(recalib=True))
        group("상태창", b1, b2, b3)
        b4 = QPushButton("영역 추가"); b4.setEnabled(current); b4.clicked.connect(lambda: home.app.calibrate("skill", pid))
        b5 = QPushButton("스킬 표시"); b5.setEnabled(current and bool(prof.regions.skill)); b5.clicked.connect(home.app.open_skills)
        group("스킬창", b4, b5)
        b6 = QPushButton("보스 디버프"); b6.setEnabled(current); b6.clicked.connect(home.app.open_boss)
        group("보스", b6)

        # 생명력·마나·스태미나 / 투아림: 한 줄씩 [영역] [설정] 지금 읽은 값 (버튼이 한 줄에 몰려 너무 길어지지 않게)
        if current:
            def line(title, region_mode, has, setting_text, open_fn, tip=""):
                h = QHBoxLayout(); h.setSpacing(8)
                t = QLabel(title); t.setFixedWidth(52); t.setStyleSheet("font-weight:600;"); h.addWidget(t)
                rb = QPushButton("영역 설정" if not has else "영역 다시"); rb.setToolTip(tip)
                rb.clicked.connect(lambda: home.app.calibrate(region_mode, pid)); h.addWidget(rb)
                sb = QPushButton(setting_text); sb.setEnabled(has); sb.clicked.connect(open_fn); h.addWidget(sb)
                lab = muted("" if has else "영역을 먼저 지정하세요"); h.addWidget(lab, 1)
                v.addLayout(h)
                return lab if has else None
            home.bars_label = line("자원", "bars", bool(prof.regions.bars), "알림 설정", home.app.open_bars,
                                   "생명력·마나·스태미나 막대")
            home.tuarim_label = line("투아림", "tuarim", bool(prof.regions.tuarim), "알림 설정", home.app.open_tuarim)


class HomeWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle(APP_NAME); self.resize(620, 560)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        head = QWidget(); hv = QHBoxLayout(head); hv.setContentsMargins(28, 24, 28, 12)
        tv = QVBoxLayout(); t = QLabel(f"{APP_NAME}  <span style='font-size:12px;color:#8b919c;font-weight:400'>v{VERSION}</span>"); t.setObjectName("title"); tv.addWidget(t)
        self.sub = QLabel(); self.sub.setObjectName("subtitle"); tv.addWidget(self.sub); hv.addLayout(tv); hv.addStretch()
        add = QPushButton("+ 캐릭터 추가"); add.setObjectName("primary"); add.clicked.connect(self.add); hv.addWidget(add)
        root.addWidget(head)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); root.addWidget(scroll, 1)
        self.inner = QWidget(); self.v = QVBoxLayout(self.inner); self.v.setContentsMargins(28, 8, 28, 16); self.v.setSpacing(10); scroll.setWidget(self.inner)

        foot = QWidget(); foot.setObjectName("footer"); fl = QHBoxLayout(foot); fl.setContentsMargins(28, 12, 28, 12)
        self.power = QCheckBox("켜기"); self.power.setChecked(app.cfg.general.active)
        self.power.setStyleSheet("font-size:15px; font-weight:700;")
        self.power.toggled.connect(lambda on: app.toggle_active(on) if on != app.cfg.general.active else None)
        fl.addWidget(self.power); fl.addWidget(muted("던전 들어갈 때 켜고 나와서 끄세요 · 트레이 아이콘 클릭으로도 됩니다")); fl.addStretch()
        self.gacha_btn = QPushButton(); self.gacha_btn.clicked.connect(app.toggle_gacha)
        self.gacha_btn.setToolTip("결과 화면을 가리는 창. 끌어서 이동 · 가장자리로 크기 · 휠로 위에서부터 줄이기. 다시 누르면 사라짐")
        fl.addWidget(self.gacha_btn)
        for text, fn in (("배치 편집", app.edit_begin), ("일반 설정", app.open_general)):
            b = QPushButton(text); b.clicked.connect(fn); fl.addWidget(b)
        root.addWidget(foot)
        tip = QLabel("이 창을 닫으면 트레이에서 계속 실행됩니다. 트레이 아이콘 클릭 = 켜기/끄기, 더블클릭 = 이 창, 우클릭 = 메뉴")
        tip.setObjectName("muted"); tip.setContentsMargins(28, 6, 28, 10); root.addWidget(tip)
        self.refresh()

    # ------------------------------------------------------------
    def update_tuarim(self):
        """현재 캐릭터 카드의 투아림·자원 표시 (읽은 값 / 샘플 수집 장수). 1초에 한 번."""
        bl = getattr(self, "bars_label", None)
        if bl is not None:
            try:
                bl.setText(self.app.bars_status() or "알림 준비 중")
            except RuntimeError:
                self.bars_label = None
        lab = getattr(self, "tuarim_label", None)
        if lab is None:
            return
        app, prof = self.app, self.app.cfg.profile()
        parts = []
        if prof and prof.tuarim_enabled:
            parts.append(app.tuarim_status() or "알림 준비 중")
        else:
            parts.append("알림 꺼짐")
        if app.tuarim is not None:
            parts.append(f"샘플 {app.tuarim.count}장" + (" (다 참)" if app.tuarim.full else ""))
        lab.setText(" · ".join(parts))

    def refresh(self):
        self.tuarim_label = None
        self.bars_label = None
        while self.v.count():
            it = self.v.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        cfg, app = self.app.cfg, self.app
        if self.power.isChecked() != cfg.general.active:
            self.power.blockSignals(True); self.power.setChecked(cfg.general.active); self.power.blockSignals(False)
        self.power.setText("켜짐 — 감시 중" if cfg.general.active else "꺼짐")
        self.gacha_btn.setText("가챠 덮개 끄기" if app.gacha_visible() else "가챠 덮개")
        if not cfg.profiles:
            self.sub.setText("캐릭터를 추가해서 시작하세요.")
            self.v.addWidget(muted("아직 캐릭터가 없습니다. 오른쪽 위 [+ 캐릭터 추가]"))
        else:
            if app.sess and app.mismatch and app.mismatch_warned:
                self.sub.setText("⚠ 상태창 항목이 변경되었습니다. 재설정해주세요 → 현재 캐릭터 카드의 [레이아웃 다시]")
            elif app.sess and app.mismatch:
                self.sub.setText("상태창 확인 중… (게임 화면이 앞에 있고 상태창이 보이면 곧 시작됩니다)")
            elif app.sess:
                self.sub.setText("준비됨 · 켜면 감시가 시작됩니다" if not cfg.general.active else "감시 중")
            else:
                self.sub.setText(app.last_error or "감시가 시작되지 않았습니다")
            for pid, prof in cfg.profiles.items():
                cur = pid == cfg.current
                rows = len(app.sess.layout.rows) if (cur and app.sess) else 0
                self.v.addWidget(ProfileCard(self, pid, prof, cur, rows, sum(1 for w in prof.watches.values() if w.enabled)))
        self.v.addStretch()
        self.update_tuarim()

    def add(self):
        name, ok = QInputDialog.getText(self, "캐릭터 추가", "캐릭터 이름")
        if ok:
            pid = self.app.cfg.add_profile(name.strip() or "캐릭터")
            self.app.cfg.save(); self.app.switch_profile(pid)

    def rename(self, pid):
        prof = self.app.cfg.profiles[pid]
        name, ok = QInputDialog.getText(self, "이름 변경", "캐릭터 이름", text=prof.name)
        if ok and name.strip():
            prof.name = name.strip(); self.app.cfg.save(); self.refresh()

    def remove(self, pid):
        prof = self.app.cfg.profiles[pid]
        if QMessageBox.question(self, "삭제", f"'{prof.name}' 설정과 레이아웃을 삭제할까요?") == QMessageBox.Yes:
            was_current = pid == self.app.cfg.current
            self.app.cfg.remove_profile(pid); layout_store.delete(pid); self.app.cfg.save()
            if was_current:
                self.app.switch_profile(self.app.cfg.current)
            else:
                self.refresh()