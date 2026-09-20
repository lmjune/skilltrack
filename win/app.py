"""
skilltrack 본체: 트레이 아이콘 + 전역 단축키 + 감시 세션 + 오버레이. 모든 설정 창을 여기서 연다.

트레이 메뉴: 감시 일시정지/재개, 오버레이 표시/숨김, 배치 편집, 감시 항목…, 일반 설정…,
             영역 설정(상태창 / 스킬창 추가), 레이아웃 다시 잡기, 종료
설정을 저장하면 재시작 없이 바로 반영된다.
"""
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import Config, CONFIG_FILE
from win.session import Session, FrameSaver, event_text, ROOT
from win.alert_overlay import AlertOverlay, set_capturable
from win.status_overlay import StatusMirrorGroup, RowOpt
from win.skill_overlay import SkillMirrorGroup
from win.window import find_window, client_rect
from win.hotkeys import Hotkeys
from ui import theme
from ui.edit_bar import EditBar

LEVEL = {"off": ("danger", 6), "keep": ("danger", 5), "under": ("warn", 5), "lost": ("warn", 5),
         "on": ("ok", 3), "extended": ("info", 3), "unextended": ("info", 3)}


def make_icon(color="#5b8cff", paused=False):
    pm = QPixmap(64, 64); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#8b919c" if paused else color)); p.setPen(Qt.NoPen)
    p.drawRoundedRect(6, 6, 52, 52, 14, 14)
    p.setBrush(QColor("white")); p.drawEllipse(20, 20, 24, 24)
    p.setBrush(QColor("#8b919c" if paused else color)); p.drawEllipse(27, 27, 10, 10)
    p.end()
    return QIcon(pm)


class App:
    def __init__(self, argv):
        self.qt = QApplication(argv)
        self.qt.setQuitOnLastWindowClosed(False)
        theme.apply(self.qt)
        from win.capture import Capture          # dxcam 은 QApplication 뒤에
        self.cap = Capture()
        self.cfg = Config.load()
        if not CONFIG_FILE.exists():
            self.cfg.save()
        self.sess = None
        self.mismatch = False
        self.overlay = self.mirror = self.skills = None
        self.client_xy = (0, 0)
        self.edit = None                          # 편집 모드 상태
        self.windows = {}                         # 열린 설정 창
        self.last_error = ""

        self.tray = QSystemTrayIcon(make_icon(paused=not self.cfg.general.active), self.qt)
        self.tray.setToolTip("skilltrack")
        self._build_menu()
        self.tray.show()
        self.tray.activated.connect(self._tray_click)

        self.hk = Hotkeys(self.qt)
        self._bind_hotkeys()
        set_capturable(self.cfg.general.capturable)

        self.timer = QTimer(); self.timer.timeout.connect(self.tick)
        self.start_session()
        self.open_home()                          # 실행하면 홈이 뜨고, 닫으면 트레이로

    # ------------------------------------------------------------ 메뉴 / 단축키
    def _build_menu(self):
        m = QMenu()
        self.a_active = QAction("", m); self.a_active.triggered.connect(self.toggle_active); m.addAction(self.a_active); self._active_text()
        m.addSeparator()
        m.addAction("열기", self.open_home)
        m.addAction("배치 편집", self.edit_begin)
        m.addAction("감시 항목…", self.open_watches)
        m.addAction("스킬 표시…", self.open_skills)
        m.addAction("일반 설정…", self.open_general)
        sub = m.addMenu("영역 설정")
        sub.addAction("상태창 영역 지정 (현재 캐릭터)", lambda: self.calibrate("status"))
        sub.addAction("스킬창 영역 추가 (현재 캐릭터)", lambda: self.calibrate("skill"))
        m.addAction("레이아웃 다시 잡기", lambda: self.start_session(recalib=True))
        m.addSeparator()
        m.addAction("종료", self.quit)
        self.tray.setContextMenu(m)

    def _tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:            # 왼쪽 클릭 = 켜기/끄기
            self.toggle_active()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.open_home()

    def _bind_hotkeys(self):
        g = self.cfg.general
        self.hk.enabled = g.hotkeys_enabled
        failed = self.hk.rebind_all({
            "켜기/끄기": (g.hotkey_toggle, self.toggle_active),
            "홈 화면": (g.hotkey_settings, self.open_home),
            "배치 편집": (g.hotkey_edit, self.edit_begin),
        })
        for f in failed:
            self.notify(f, "warn")

    def notify(self, text, level="info", dur=4.0):
        print(f"[{datetime.now():%H:%M:%S}] {text}")
        if self.overlay:
            self.overlay.push(text, level, dur, sound=False)
        else:
            self.tray.showMessage("skilltrack", text)

    # ------------------------------------------------------------ 세션
    def start_session(self, recalib=False):
        self.timer.stop(); self.sess = None; self.last_error = ""
        self.cfg = Config.load()
        g, prof = self.cfg.general, self.cfg.profile()
        if not prof:
            self.last_error = "캐릭터가 없습니다"; self._refresh_home(); return
        if not prof.regions.status:
            self.last_error = f"'{prof.name}' 상태창 영역이 없습니다 → [영역 설정]"; self._refresh_home(); return
        hwnd = find_window(g.window_title)
        if not hwnd:
            self.last_error = f"게임 창을 못 찾음: '{g.window_title}'"; self.tray.showMessage("skilltrack", self.last_error); self._refresh_home(); return
        cx, cy, _, _ = client_rect(hwnd)
        self.client_xy = (cx, cy)
        x, y, w, h = prof.regions.status
        try:
            saver = FrameSaver(ROOT / "tests" / "fixtures" / "auto", enabled=g.diag_save)
            self.sess = Session(self.cap, (cx + x, cy + y, w, h), tuple(prof.regions.status), pid=self.cfg.current,
                                watch_opts=prof.watch_opts(), recalib=recalib, saver=saver)
        except RuntimeError as e:
            self.last_error = str(e); self.tray.showMessage("skilltrack", str(e)); self._refresh_home(); return
        for n in self.sess.notes:
            print(n)
        self.mismatch = self.sess.verify_ratio is not None and self.sess.verify_ratio < 0.6
        self._rebuild_overlays()
        if self.mismatch:
            # 고정 목록이 바뀌었거나 다른 캐릭터. 틀린 레이아웃으로 감시하지 않는다
            self.last_error = f"'{prof.name}' 상태창 항목이 변경되었습니다. 재설정해주세요 (홈 → 레이아웃 다시)"
            self.tray.showMessage("skilltrack", self.last_error)
            if self.active:
                self.notify("상태창 항목이 변경됨 — 홈에서 '레이아웃 다시'", "warn", 8)
            self._refresh_home(); return
        self.timer.start(int(1000 / g.fps))
        if self.cfg.general.active:
            self.notify(f"{prof.name} — 감시 {len(self.sess.tracker.tracks)}개", "info", 2.5)
        self._refresh_home()

    def switch_profile(self, pid):
        if pid not in self.cfg.profiles:
            return
        self.cfg.current = pid; self.cfg.save()
        if self.overlay:
            self.overlay.close(); self.overlay = None
        if self.mirror:
            self.mirror.close(); self.mirror = None
        self.start_session()
        if not self.overlay:
            self._rebuild_overlays()

    def _rebuild_overlays(self):
        ov = self.cfg.overlays
        if self.overlay:
            self.overlay.close()
        if self.mirror:
            self.mirror.close(); self.mirror = None
        if self.skills:
            self.skills.close(); self.skills = None
        self.overlay = AlertOverlay(pos=tuple(ov.alert_pos), width=ov.alert_width, font_pt=ov.alert_font_pt)
        prof0 = self.cfg.profile()
        if prof0 and prof0.skill_items and prof0.regions.skill:
            self.skills = SkillMirrorGroup(self.cap, self.client_xy, prof0.regions.skill, prof0.skill_items,
                                           default_scale=ov.skill_scale, opacity=ov.skill_opacity, origin=tuple(ov.skill_pos))
        prof = self.cfg.profile()
        mirror_rows = prof.mirror_rows if (self.sess and prof) else []
        if mirror_rows:
            opts = [RowOpt(m.row, m.icon, m.name, m.time, m.only_active, m.dim_inactive, m.pos, m.scale) for m in mirror_rows]
            labels = {r: (w.label or f"행 {r}") for r, w in prof.watches.items()}
            self.mirror = StatusMirrorGroup(self.sess.layout, opts, default_scale=ov.mirror_scale, opacity=ov.mirror_opacity,
                                            origin=tuple(ov.mirror_pos), labels=labels)
        self._apply_show(self.active)

    @property
    def active(self):
        return self.cfg.general.active

    def tick(self):
        if not self.active or not self.sess or self.mismatch:
            return
        if self.cfg.general.hide_when_inactive and not self.edit:
            import win32gui
            fg = find_window(self.cfg.general.window_title)
            self._apply_show(bool(fg) and win32gui.GetForegroundWindow() == fg)
        if self.skills:
            self.skills.update()
        frame = self.cap.grab(self.sess.region)
        if frame is None:
            return
        r = self.sess.process(frame)
        if self.mirror:
            self.mirror.update_from(frame, r)
        for n in r.notes:
            print(f"[{datetime.now():%H:%M:%S}] {n}")
        g = self.cfg.general
        for ev in r.events:
            if ev.kind not in LEVEL:
                continue
            level, dur = LEVEL[ev.kind]
            text = f"{ev.label} {event_text(ev)}"
            print(f"[{datetime.now():%H:%M:%S}] {text}")
            self.overlay.push(text, level, dur, sound=g.sound, sound_file=g.sound_file or None)

    # ------------------------------------------------------------ 마스터 스위치
    def _active_text(self):
        self.a_active.setText("끄기 (오버레이·알림 전부 중지)" if self.cfg.general.active else "켜기 (감시·알림·오버레이 시작)")

    def toggle_active(self, on=None):
        g = self.cfg.general
        g.active = (not g.active) if on is None else bool(on)
        self.cfg.save(); self._active_text()
        self.tray.setIcon(make_icon(paused=not g.active))
        if g.active and not self.sess:
            self.start_session()
        self._apply_show(g.active)
        if g.active and self.mismatch:
            self.notify("상태창 항목이 변경됨 — 홈에서 '레이아웃 다시'", "warn", 8)
        elif g.active:
            self.notify("켜짐 — 감시 중", "ok", 2.0)
        self._refresh_home()

    def _apply_show(self, on):
        if self.overlay and self.overlay.isVisible() != bool(on):
            self.overlay.setVisible(bool(on))
        for grp in (self.mirror, self.skills):
            if grp:
                grp.set_visible(bool(on))

    # ------------------------------------------------------------ 배치 편집
    def _groups(self):
        return [g for g in (self.mirror, self.skills) if g]

    def edit_begin(self):
        if self.edit:
            return
        if not self.overlay:
            self._rebuild_overlays()
        ov = self.cfg.overlays
        self._apply_show(True)
        self.edit = {"backup": (self.overlay.pos(), [g.positions() for g in self._groups()], ov.mirror_opacity, ov.skill_opacity)}
        self.overlay.set_edit(True)
        for g in self._groups():
            g.set_edit(True)
        bar = EditBar(ov.mirror_scale, ov.mirror_opacity, has_mirror=self.mirror is not None,
                      skill_scale=ov.skill_scale, skill_opacity=ov.skill_opacity, has_skill=self.skills is not None)
        bar.scale_changed.connect(lambda v: self.mirror and self.mirror.set_scale_all(v))
        bar.opacity_changed.connect(lambda v: self.mirror and self.mirror.set_opacity_all(v))
        bar.stack.connect(lambda: self.mirror and self.mirror.stack_vertical())
        bar.skill_scale_changed.connect(lambda v: self.skills and self.skills.set_scale_all(v))
        bar.skill_opacity_changed.connect(lambda v: self.skills and self.skills.set_opacity_all(v))
        bar.skill_stack.connect(lambda: self.skills and self.skills.stack_vertical())
        bar.saved.connect(lambda: self.edit_end(True)); bar.cancelled.connect(lambda: self.edit_end(False))
        bar.show(); bar.raise_(); bar.activateWindow(); self.edit["bar"] = bar
        self.edit["sample"] = QTimer(); self.edit["sample"].timeout.connect(self._edit_sample); self.edit["sample"].start(1500); self._edit_sample()

    def _edit_sample(self):
        if self.edit and self.overlay:
            self.overlay.push("마나실드 꺼짐 (예시)", "danger", 2.0, sound=False)
            self.overlay.push("전장의 서곡 30초 미만 (예시)", "warn", 2.0, sound=False)

    def edit_end(self, save):
        if self.edit and self.edit.get("sample"):
            self.edit["sample"].stop()
        ov, prof = self.cfg.overlays, self.cfg.profile()
        if save:
            ov.alert_pos = [self.overlay.x(), self.overlay.y()]
            if prof:
                if self.mirror:
                    by = {m.row: m for m in prof.mirror_rows}
                    for key, pos, sc in self.mirror.positions():
                        if key[1] in by:
                            by[key[1]].pos, by[key[1]].scale = pos, sc
                if self.skills:
                    by = {(s.region, s.slot): s for s in prof.skill_items}
                    for key, pos, sc in self.skills.positions():
                        k = (key[1], key[2])
                        if k in by:
                            by[k].pos, by[k].scale = pos, sc
            bar = self.edit["bar"]
            ov.mirror_opacity, ov.mirror_scale = round(bar.opacity.value(), 2), round(bar.scale.value(), 2)
            ov.skill_opacity, ov.skill_scale = round(bar.skill_opacity.value(), 2), round(bar.skill_scale.value(), 2)
            self.cfg.save()
        else:
            apos, gpos, mop, sop = self.edit["backup"]
            self.overlay.move(apos)
            for g, saved in zip(self._groups(), gpos):
                g.restore(saved); g.set_opacity_all(sop if g is self.skills else mop)
        self.overlay.set_edit(False)
        for g in self._groups():
            g.set_edit(False)
        self.edit["bar"].close(); self.edit = None
        self._apply_show(self.active)

    # ------------------------------------------------------------ 설정 창
    def open_home(self):
        from ui.home import HomeWindow
        self._show(HomeWindow(self), "home")

    def _refresh_home(self):
        h = self.windows.get("home")
        if h is not None:
            try:
                h.refresh()
            except RuntimeError:
                self.windows.pop("home", None)

    def open_watches(self):
        if not self.sess:
            self.open_home(); return
        from ui.watches import WatchesWindow
        frame = self.cap.grab_sure(self.sess.region)
        w = WatchesWindow(self.cfg, self.cfg.profile(), self.sess.layout, frame, on_saved=self.start_session)
        self._show(w, "watches")

    def open_skills(self):
        prof = self.cfg.profile()
        if not prof:
            return
        from ui.skills import SkillsWindow
        cx, cy = self.client_xy
        hwnd = find_window(self.cfg.general.window_title)
        if hwnd:
            cx, cy, _, _ = client_rect(hwnd); self.client_xy = (cx, cy)
        frames = {}
        for rg in prof.regions.skill:
            x, y, w, h = rg["rect"]
            f = self.cap.grab_sure((cx + x, cy + y, w, h))
            frames[rg["id"]] = (f, x, y)
        w = SkillsWindow(self.cfg, prof, frames, on_saved=self._rebuild_overlays, app=self)
        self._show(w, "skills")

    def open_general(self):
        from ui.general import GeneralWindow
        w = GeneralWindow(self.cfg, on_saved=self._general_saved)
        self._show(w, "general")

    def _general_saved(self):
        self.cfg = Config.load()
        self._bind_hotkeys()
        set_capturable(self.cfg.general.capturable)
        if self.sess:
            self.timer.start(int(1000 / self.cfg.general.fps))
            self.sess.saver.enabled = self.cfg.general.diag_save
        self.notify("일반 설정 저장", "info", 2.0)

    def calibrate(self, mode, pid=None, redo_id=None):
        from ui.calibrate import Calibrator
        pid = pid or self.cfg.current
        prof = self.cfg.profiles.get(pid)
        if not prof:
            return
        hwnd = find_window(self.cfg.general.window_title)
        if not hwnd:
            self.tray.showMessage("skilltrack", "게임 창을 못 찾음"); return
        self._was_active = self.cfg.general.active
        if self._was_active:
            self.toggle_active(False)                   # 드래그 중엔 오버레이·감시 끔
        w = Calibrator(mode, self.cap, client_rect(hwnd), self.cfg, prof, redo_id=redo_id)
        w.destroyed.connect(lambda: self._after_calibrate(mode, pid))
        self._show(w, "calib")

    def _after_calibrate(self, mode, pid):
        self.cfg = Config.load()
        if mode == "skill":
            self._rebuild_overlays()
        if mode == "status" and self.cfg.profiles.get(pid) and self.cfg.profiles[pid].regions.status:
            if pid != self.cfg.current:
                self.switch_profile(pid)
            else:
                self.start_session(recalib=True)
        if self._was_active:
            self.toggle_active(True)
        self._refresh_home()

    def _show(self, w, key):
        old = self.windows.pop(key, None)
        if old is not None:
            try:
                old.close()
            except RuntimeError:
                pass                                   # 이미 닫혀서 파괴된 창
        self.windows[key] = w
        w.setAttribute(Qt.WA_DeleteOnClose)
        w.destroyed.connect(lambda *_: self.windows.pop(key, None) if self.windows.get(key) is w else None)
        w.show(); w.raise_(); w.activateWindow()

    def quit(self):
        self.timer.stop(); self.hk.unbind_all(); self.tray.hide(); self.qt.quit()

    def exec(self):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        ka = QTimer(); ka.timeout.connect(lambda: None); ka.start(200)
        return self.qt.exec()


if __name__ == "__main__":
    sys.exit(App(sys.argv).exec())