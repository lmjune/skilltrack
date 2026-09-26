"""
skilltrack 본체: 트레이 아이콘 + 전역 단축키 + 감시 세션 + 오버레이. 모든 설정 창을 여기서 연다.

트레이 메뉴: 감시 일시정지/재개, 오버레이 표시/숨김, 배치 편집, 감시 항목…, 일반 설정…,
             영역 설정(상태창 / 스킬창 추가), 레이아웃 다시 잡기, 종료
설정을 저장하면 재시작 없이 바로 반영된다.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

sys.path.insert(0, str(Path(__file__).parent.parent))
from core import screen
from core.config import Config, CONFIG_FILE, skill_capture_rect
from win.session import Session, FrameSaver, event_text
from core.paths import ASSETS, DIAG, VERSION, APP_NAME
from win.alert_overlay import AlertOverlay, set_capturable
from win.status_overlay import StatusMirrorGroup, RowOpt
from win.skill_overlay import SkillMirrorGroup
from win.boss_session import BossSession, boss_rect, debuff_event_text
from win.boss_overlay import BossOverlay
from win.window import find_window, client_rect
from win.hotkeys import Hotkeys
from ui import theme
from ui.edit_bar import EditBar

LEVEL = {"off": ("danger", 6), "keep": ("danger", 5), "under": ("warn", 5), "lost": ("warn", 5),
         "on": ("ok", 3), "extended": ("info", 3), "unextended": ("info", 3), "resync": ("ok", 3)}


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
        self.mismatch_since = None                # 레이아웃 불일치가 시작된 시각 (재확인 중). 경고는 10초 지속 시 1회
        self.mismatch_warned = False
        self.overlay = self.mirror = self.skills = None
        self.boss = None                          # BossSession (프로필에서 켰을 때)
        self.boss_ov = None                       # BossOverlay
        self.client_xy = (0, 0)
        self.client_wh = (3840, 2160)
        self._last_sync = 0.0                     # _sync_client 마지막 확인 시각
        self.edit = None                          # 편집 모드 상태
        self.windows = {}                         # 열린 설정 창
        self.last_error = ""

        self.tray = QSystemTrayIcon(make_icon(paused=not self.cfg.general.active), self.qt)
        self.tray.setToolTip(f"{APP_NAME} {VERSION}")
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
        m.addAction("보스 디버프…", self.open_boss)
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
            self.tray.showMessage(APP_NAME, text)

    # ------------------------------------------------------------ 세션
    def start_session(self, recalib=False):
        self.timer.stop(); self.sess = None; self.last_error = ""
        self.mismatch, self.mismatch_since, self.mismatch_warned = False, None, False
        self.cfg = Config.load()
        g, prof = self.cfg.general, self.cfg.profile()
        screen.set_screen(g.ui_variant)             # UI 크기 변형: 치수 배율·시간 글자 세트
        if not prof:
            self.last_error = "캐릭터가 없습니다"; self._refresh_home(); return
        hwnd = find_window(g.window_title)
        if not hwnd:
            self.last_error = f"게임 창을 못 찾음: '{g.window_title}'"; self.tray.showMessage(APP_NAME, self.last_error); self._refresh_home(); return
        cx, cy, cw, ch = client_rect(hwnd)
        self.client_xy, self.client_wh = (cx, cy), (cw, ch)
        # dxcam 은 막 만들어진 직후 검은/이전 프레임을 주는 일이 잦다 → 몇 장 버리고 시작 (첫 판정이 그걸로 틀리는 것 방지)
        for _ in range(3):
            self.cap.grab(); time.sleep(0.05)
        # 상태창 감시는 선택: 영역이 없거나 준비에 실패해도 스킬 표시·보스 디버프는 따로 돈다
        if prof.regions.status:
            x, y, w, h = prof.regions.status
            try:
                saver = FrameSaver(DIAG / "auto", enabled=g.diag_save)
                self.sess = Session(self.cap, (cx + x, cy + y, w, h), tuple(prof.regions.status), pid=self.cfg.current,
                                    watch_opts=prof.watch_opts(), recalib=recalib, saver=saver)
            except RuntimeError as e:
                self.last_error = str(e); self.tray.showMessage(APP_NAME, str(e))
            if self.sess:
                for n in self.sess.notes:
                    print(n)
                # 안 맞아도 틱은 돌린다: 상태창 감시만 보류하고 1초마다 다시 확인 (시작 직후 검은 프레임, 로딩 화면, 밝은 곳 등 일시적 원인).
                # 진짜로 바뀐 것(다른 캐릭터·고정 목록 변경)은 10초 넘게 계속 안 맞을 때 경고
                self.mismatch = self.sess.verify_ratio is not None and self.sess.verify_ratio < 0.6
                self.mismatch_since = time.time() if self.mismatch else None
        else:
            self.last_error = f"'{prof.name}' 상태창 영역이 없습니다 → [영역 설정] (스킬 표시·보스 디버프는 동작)"
        self._start_boss(prof)
        self._rebuild_overlays()
        if not (self.sess or self.boss or self.skills):
            self._refresh_home(); return            # 돌릴 게 하나도 없음
        self.timer.start(int(1000 / g.fps))
        if self.cfg.general.active and self.sess and not self.mismatch:
            self.notify(f"{prof.name} — 감시 {len(self.sess.tracker.tracks)}개", "info", 2.5)
        self._refresh_home()

    def _recheck_layout(self, frame):
        """불일치 상태에서 1초마다: 맞으면 감시 시작, 10초 넘게 안 맞으면 경고 1회."""
        from core import layout_store
        now = time.time()
        if now - getattr(self, "_recheck_at", 0) < 1.0:
            return
        self._recheck_at = now
        ratio = layout_store.verify(frame, self.sess.sites)
        if ratio >= 0.6:
            self.mismatch, self.mismatch_since, self.last_error = False, None, ""
            print(f"[{datetime.now():%H:%M:%S}] 레이아웃 확인됨 ({ratio:.0%}) — 감시 시작")
            if self.active:
                self.notify(f"{self.cfg.profile().name} — 감시 {len(self.sess.tracker.tracks)}개", "info", 2.5)
            self._refresh_home()
        elif not self.mismatch_warned and now - self.mismatch_since > 10:
            self.mismatch_warned = True
            prof = self.cfg.profile()
            self.last_error = f"'{prof.name}' 상태창 항목이 변경되었습니다. 재설정해주세요 (홈 → 레이아웃 다시)"
            self.tray.showMessage(APP_NAME, self.last_error)
            if self.active:
                self.notify("상태창 항목이 변경됨 — 홈에서 '레이아웃 다시'", "warn", 8)
            self._refresh_home()

    def _start_boss(self, prof):
        """보스 디버프 세션. 프로필에서 껐으면 None. 감시 목록이 비어도 인식·아이콘 수집은 한다."""
        self.boss = None
        if not prof or not prof.boss_enabled:
            return
        try:
            saver = FrameSaver(DIAG / "boss" / "auto", enabled=self.cfg.general.diag_save,
                               reasons=("newicon", "nostrip", "nopanel", "dropped", "manual"))
            self.boss = BossSession(prof.boss_watch_list({}), saver=saver, learn=self.cfg.general.boss_learn_icons)
            self.boss.set_watches(prof.boss_watch_list(self.boss.icons.meta))
        except Exception as e:
            print(f"보스 세션 실패: {e}")

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
        if self.boss_ov:
            self.boss_ov.close(); self.boss_ov = None
        self.overlay = AlertOverlay(pos=tuple(ov.alert_pos), width=ov.alert_width, font_pt=ov.alert_font_pt)
        if self.boss:
            self.boss_ov = BossOverlay(self.boss.icons, pos=tuple(ov.boss_pos), scale=ov.boss_scale, opacity=ov.boss_opacity)
        prof0 = self.cfg.profile()
        if prof0 and prof0.skill_items and prof0.regions.skill:
            self.skills = SkillMirrorGroup(self.cap, self.client_xy, prof0.regions.skill, prof0.skill_items,
                                           default_scale=ov.skill_scale, opacity=ov.skill_opacity, origin=tuple(ov.skill_pos), smooth=ov.skill_smooth)
        prof = self.cfg.profile()
        mirror_rows = prof.mirror_rows if (self.sess and prof) else []
        if mirror_rows:
            opts = [RowOpt(m.row, m.icon, m.name, m.time, m.only_active, m.dim_inactive, m.pos, m.scale) for m in mirror_rows]
            labels = {r: (w.label or f"행 {r}") for r, w in prof.watches.items()}
            self.mirror = StatusMirrorGroup(self.sess.layout, opts, default_scale=ov.mirror_scale, opacity=ov.mirror_opacity,
                                            origin=tuple(ov.mirror_pos), labels=labels)
        # 저장된 위치/기본 위치가 이 모니터 기준으로 화면 밖이면 안으로 (4K 좌표 기본값, 윈도우 배율, 모니터 변경)
        self.overlay.ensure_on_screen()
        if self.boss_ov:
            self.boss_ov.ensure_on_screen()
        for g in (self.skills, self.mirror):
            if g:
                g.ensure_visible()
        self._apply_show(self.active)

    @property
    def active(self):
        return self.cfg.general.active

    def tick(self):
        if not self.active:
            return
        if self.cfg.general.hide_when_inactive and not self.edit:
            import win32gui
            fg = find_window(self.cfg.general.window_title)
            front = bool(fg) and win32gui.GetForegroundWindow() == fg
            self._apply_show(front)
            if not front:
                return          # 게임이 뒤에 있으면 인식도 쉼 (다른 창 픽셀을 읽지 않게). 시간은 추정 타이머가 벽시계로 이어감
        # 한 틱에 전체 화면을 한 번만 캡처해서 잘라 쓴다.
        # (dxcam 은 새 프레임이 없으면 None 을 주는데, 영역별로 따로 grab 하면 앞의 grab 이 '새 프레임'을
        #  소비해 뒤의 상태창 grab 이 자주 None → 처리가 드문드문 → 시간 추정이 어긋남)
        if self._sync_client():
            return              # 게임 창이 움직였거나 크기가 바뀜 → 세션을 새 좌표로 다시 시작했음
        full = self.cap.grab()
        if full is None:
            return
        # 스킬 표시·보스 디버프는 상태창과 독립 (상태창 영역이 없거나 레이아웃이 안 맞아도 동작)
        if self.skills:
            self.skills.update(full)
        if self.boss:
            self._boss_tick(full)
        if not self.sess:
            return
        x, y, w, h = self.sess.region
        frame = full[y:y + h, x:x + w]
        if frame.shape[0] != h or frame.shape[1] != w:
            return
        if self.mismatch:
            self._recheck_layout(frame)          # 맞을 때까지 상태창 감시만 보류 (틀린 레이아웃으로 읽지 않는다)
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

    def _sync_client(self):
        """1초마다 게임 창 클라이언트 좌표를 다시 읽는다. 움직이거나 크기가 바뀌면 세션 재시작
        (저장된 영역은 전부 클라이언트 기준이라 재캘리브레이션은 필요 없다). 배치 편집 중에는 건드리지 않는다."""
        now = time.time()
        if self.edit or now - self._last_sync < 1.0:
            return False
        self._last_sync = now
        hwnd = find_window(self.cfg.general.window_title)
        if not hwnd:
            return False
        cx, cy, cw, ch = client_rect(hwnd)
        if cw <= 0 or ch <= 0 or cx <= -30000:      # 최소화된 창 (-32000, -32000)
            return False
        if (cx, cy) != self.client_xy or (cw, ch) != self.client_wh:
            print(f"[{datetime.now():%H:%M:%S}] 게임 창 이동/크기 변경 → {cw}×{ch} @ ({cx},{cy}), 세션 재시작")
            self.start_session()
            return True
        return False

    def _boss_tick(self, full):
        prof = self.cfg.profile()
        bx, by, bw, bh = tuple(prof.regions.boss) if (prof and prof.regions.boss) else boss_rect(*self.client_wh)
        cx, cy = self.client_xy                      # 영역은 클라이언트 기준, full 은 모니터 전체
        bframe = full[cy + by:cy + by + bh, cx + bx:cx + bx + bw]
        if bframe.shape[0] != bh or bframe.shape[1] != bw:
            return
        br = self.boss.process(bframe)
        for n in br.notes:
            print(f"[{datetime.now():%H:%M:%S}] {n}")
        g = self.cfg.general
        for ev in br.events:
            text = f"{ev.label} {debuff_event_text(ev)}".strip() if ev.kind != "burst" else debuff_event_text(ev)
            print(f"[{datetime.now():%H:%M:%S}] [보스] {text}")
            if ev.kind == "burst":
                self.overlay.push(text, "danger", 5.0, sound=g.sound, sound_file=g.sound_file or None)
            elif ev.kind in ("start", "end"):
                self.overlay.push(text, "info", 2.5, sound=False)
        if self.boss_ov:
            self.boss_ov.update_from(br.shown)

    # ------------------------------------------------------------ 마스터 스위치
    def _active_text(self):
        self.a_active.setText("끄기 (오버레이·알림 전부 중지)" if self.cfg.general.active else "켜기 (감시·알림·오버레이 시작)")

    def toggle_active(self, on=None):
        g = self.cfg.general
        g.active = (not g.active) if on is None else bool(on)
        self.cfg.save(); self._active_text()
        self.tray.setIcon(make_icon(paused=not g.active))
        if g.active and not self.timer.isActive():
            self.start_session()
        self._apply_show(g.active)
        if g.active and self.mismatch and self.mismatch_warned:
            self.notify("상태창 항목이 변경됨 — 홈에서 '레이아웃 다시'", "warn", 8)
        elif g.active:
            self.notify("켜짐 — 감시 중", "ok", 2.0)
        self._refresh_home()

    def _apply_show(self, on):
        if self.overlay and self.overlay.isVisible() != bool(on):
            self.overlay.setVisible(bool(on))
        if self.boss_ov and self.boss_ov.isVisible() != bool(on):
            self.boss_ov.setVisible(bool(on))
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
        self.edit = {"backup": (self.overlay.pos(), [g.positions() for g in self._groups()], ov.mirror_opacity, ov.skill_opacity,
                                (self.boss_ov.pos(), self.boss_ov.scale) if self.boss_ov else None)}
        self.overlay.set_edit(True)
        if self.boss_ov:
            self.boss_ov.set_edit(True)
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
            if self.boss_ov:
                ov.boss_pos, ov.boss_scale = [self.boss_ov.x(), self.boss_ov.y()], round(self.boss_ov.scale, 2)
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
            apos, gpos, mop, sop, bback = self.edit["backup"]
            self.overlay.move(apos)
            if self.boss_ov and bback:
                self.boss_ov.move(bback[0]); self.boss_ov.set_scale(bback[1])
            for g, saved in zip(self._groups(), gpos):
                g.restore(saved); g.set_opacity_all(sop if g is self.skills else mop)
        self.overlay.set_edit(False)
        if self.boss_ov:
            self.boss_ov.set_edit(False)
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
            x, y, w, h = skill_capture_rect(rg)
            try:
                f = self.cap.grab_sure((cx + x, cy + y, w, h))
            except Exception as ex:
                print(f"[{datetime.now():%H:%M:%S}] 스킬창 {rg['id']} 캡처 실패: {ex}")
                continue
            frames[rg["id"]] = (f, x, y)
        w = SkillsWindow(self.cfg, prof, frames, on_saved=self._rebuild_overlays, app=self)
        self._show(w, "skills")

    def open_boss(self):
        prof = self.cfg.profile()
        if not prof:
            self.open_home(); return
        from ui.boss import BossWindow
        from core.bossbar import IconLib
        icons = self.boss.icons if self.boss else IconLib(ASSETS / "boss_icons")
        icons.load()                                       # 전투 중 자동 등록된 것 반영
        w = BossWindow(self.cfg, prof, icons, on_saved=self._boss_saved)
        self._show(w, "boss")

    def _boss_saved(self):
        self.cfg = Config.load()
        prof = self.cfg.profile()
        self._start_boss(prof)
        self._rebuild_overlays()
        self.notify(f"보스 디버프 감시 {len(prof.boss_watches) if prof and prof.boss_enabled else 0}개", "info", 2.0)
        self._refresh_home()

    def open_general(self):
        from ui.general import GeneralWindow
        w = GeneralWindow(self.cfg, on_saved=self._general_saved)
        self._show(w, "general")

    def _general_saved(self):
        old = screen.current().key
        self.cfg = Config.load()
        if self.cfg.general.ui_variant != old:        # UI 크기가 바뀌면 검출 규칙·글자 세트가 달라짐 → 세션 다시
            self.notify("UI 크기 변경 → 다시 시작합니다. 상태창이 안 맞으면 [영역 설정]을 다시 하세요", "info", 4.0)
            self.start_session()
            return
        self._bind_hotkeys()
        set_capturable(self.cfg.general.capturable)
        if self.skills:
            self._rebuild_overlays()
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
            self.tray.showMessage(APP_NAME, "게임 창을 못 찾음"); return
        screen.set_screen(self.cfg.general.ui_variant)
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