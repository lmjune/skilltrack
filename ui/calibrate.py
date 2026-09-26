"""
영역 드래그 캘리브레이션. 게임 위에 반투명 막을 씌우고 드래그하면 실시간으로 검출 결과가 그려진다.

사용법:
  python ui/calibrate.py status          # 상태창 영역
  python ui/calibrate.py skill           # 스킬창 영역 하나 추가 (여러 번 실행하면 여러 개)

조작: 드래그 = 영역, Enter = 확정·저장, R = 다시, Esc = 취소
"""
import ctypes
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).parent.parent))
from core import screen
from core.config import Config, skill_capture_rect
from core.rows import detect_rows
from core.status import parse_rows
from core.grid import detect_grid_in
from win.window import find_window, client_rect

HINT = {
    "status": "시간이 표시되는 버프를 하나 켜두고, 상태창을 넉넉히 감싸게 드래그하세요 (좌우는 자동으로 맞춰집니다)",
    "skill":  "스킬창 하나를 감싸게 드래그하세요 (대충 그려도 격자를 알아서 찾습니다)",
}


class Calibrator(QWidget):
    def __init__(self, mode, cap, client, cfg, profile, redo_id=None):
        super().__init__()
        self.mode, self.cap, self.client, self.cfg, self.prof, self.redo_id = mode, cap, client, cfg, profile, redo_id
        self.start = self.end = None
        self.result = None            # 검출 결과 (화면 절대 좌표 박스 리스트, 설명)
        self.last_detect = 0.0
        self.pending = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        scr = QApplication.primaryScreen().geometry()
        self.setGeometry(scr)
        self.font_ = QFont("Malgun Gothic", 14, QFont.Bold)
        self.timer = QTimer(self); self.timer.timeout.connect(self._maybe_detect); self.timer.start(60)
        self.showFullScreen()
        # 이 창(어두운 막·박스)이 캡처에 찍히면 검출이 깨진다 → 캡처 제외
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11)
        except Exception:
            pass

    # ------------------------------------------------------------ 입력
    def mousePressEvent(self, e):
        self.start = self.end = e.position().toPoint(); self.result = None; self.update()

    def mouseMoveEvent(self, e):
        if self.start is not None and e.buttons() & Qt.LeftButton:
            self.end = e.position().toPoint(); self.pending = True; self.update()

    def mouseReleaseEvent(self, e):
        if self.start is not None:
            self.end = e.position().toPoint(); self.pending = True; self._detect(); self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() == Qt.Key_R:
            self.start = self.end = None; self.result = None; self.update()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.result and self.result.get("ok"):
            self._save(); self.close()

    def rect(self) -> QRect | None:
        if self.start is None or self.end is None:
            return None
        return QRect(self.start, self.end).normalized()

    # ------------------------------------------------------------ 검출
    def _maybe_detect(self):
        if self.pending and time.time() - self.last_detect > 0.15:
            self._detect()

    def _detect(self):
        self.pending = False; self.last_detect = time.time()
        r = self.rect()
        if r is None or r.width() < 20 or r.height() < 20:
            self.result = None; return
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        try:
            if self.mode == "status":
                crop = self.cap.grab_sure((x, y, w, h))
                L = detect_rows(crop)
                if L is None:
                    self.result = {"ok": False, "msg": "행을 못 찾음. 상태창이 잘 보이는 곳(어두운 배경)에서, 패널 폭에 맞게"
                                                        f" (일반 설정의 UI 크기: {screen.current().label})"}
                    return
                if not screen.pitch_matches(L.pitch):
                    seen = screen.guess_from_pitch(L.pitch)
                    self.result = {"ok": False, "msg": f"행 간격이 {L.pitch}px — 게임 UI 크기{f'({seen})' if seen else ''}가 "
                                                        f"일반 설정의 'UI 크기 변경'({screen.current().label})과 다릅니다. 설정을 맞추고 다시 하세요"}
                    return
                # 저장 폭 = 검출된 글자 끝까지 (버프 하나 켜두면 시간 글자까지 포함됨). 드래그 폭은 탐색 범위일 뿐
                left = max(0, L.icon_x - 6)
                right = min(w, L.right + 8)
                has_time = any(s.time_range for s in parse_rows(crop, L))
                note = "시간 글자까지 포함" if has_time else "⚠ 시간 글자가 안 보임 — 시간 표시되는 버프 하나 켜고 다시 하세요"
                boxes = []
                for i, rw in enumerate(L.rows):
                    ix, iy, iw, ih = rw.icon
                    boxes.append((x + left, y + iy - 1, right - left, ih + 2, i in L.sections[0]))
                self.result = {"ok": has_time, "boxes": boxes,
                               "msg": f"행 {len(L.rows)}개 (고정 {len(L.sections[0])}개), {note}" + (" — Enter 저장 / R 다시 / Esc 취소" if has_time else ""),
                               "rect": (x + left, y, right - left, h)}
            else:
                full = self.cap.grab_sure((0, 0, self.width(), self.height()))
                g = detect_grid_in(full, (x, y, w, h))
                if g is None:
                    self.result = {"ok": False, "msg": "격자를 못 찾음. 스킬 아이콘들을 감싸게 다시"}
                    return
                boxes = [(sx - 1, sy - 1, sw + 2, sh + 2, True) for _, (sx, sy, sw, sh) in g.all_slots()]
                self.result = {"ok": True, "boxes": boxes, "grid": g,
                               "msg": f"슬롯 {g.cols}x{g.rows} = {g.cols * g.rows}개 — Enter 저장 / R 다시 / Esc 취소",
                               "rect": (x, y, w, h)}
        except Exception as ex:
            self.result = {"ok": False, "msg": f"오류: {ex}"}

    # ------------------------------------------------------------ 저장
    def _save(self):
        cx, cy = self.client[0], self.client[1]
        x, y, w, h = self.result["rect"]
        rel = [x - cx, y - cy, w, h]
        if self.mode == "status":
            self.prof.regions.status = rel
        else:
            g = self.result["grid"]
            entry = {"rect": rel, "grid": {"xs": [int(v) - cx for v in g.xs], "ys": [int(v) - cy for v in g.ys], "w": int(g.w), "h": int(g.h)}}
            entry["rect"] = list(skill_capture_rect(entry))     # 드래그 rect → 격자 전체를 덮는 rect (슬롯이 잘리지 않게)
            if self.redo_id and any(r["id"] == self.redo_id for r in self.prof.regions.skill):
                for r in self.prof.regions.skill:
                    if r["id"] == self.redo_id:
                        r.update(entry)                      # 같은 id 유지 → 표시 설정 그대로
            else:
                used = {r["id"] for r in self.prof.regions.skill}
                n = 1
                while f"skill{n}" in used:
                    n += 1
                self.prof.regions.skill.append({"id": f"skill{n}", **entry})
        self.cfg.save()
        print(f"저장: {self.mode} {rel}")

    # ------------------------------------------------------------ 그리기
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect_all(), QColor(0, 0, 0, 70))
        p.setFont(self.font_)
        r = self.rect()
        if r:
            p.fillRect(r, QColor(0, 0, 0, 0))
            p.setCompositionMode(QPainter.CompositionMode_Clear); p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(255, 60, 60), 2)); p.setBrush(Qt.NoBrush); p.drawRect(r)
        if self.result and self.result.get("ok"):
            for bx, by, bw, bh, strong in self.result["boxes"]:
                p.setPen(QPen(QColor(0, 255, 0) if strong else QColor(150, 150, 150), 1)); p.drawRect(bx, by, bw, bh)
        msg = self.result["msg"] if self.result else HINT[self.mode]
        p.setPen(QPen(QColor(255, 255, 255)))
        p.fillRect(QRect(20, 20, 1400, 44), QColor(0, 0, 0, 170))
        p.drawText(QRect(32, 20, 1380, 44), Qt.AlignVCenter | Qt.AlignLeft, msg)
        p.end()

    def rect_all(self):
        return QRect(0, 0, self.width(), self.height())


def main(mode):
    app = QApplication(sys.argv)
    from win.capture import Capture
    cfg = Config.load()
    prof = cfg.profile()
    if not prof:
        print("먼저 트레이 앱(python win/run.py)에서 캐릭터를 추가하세요"); return
    hwnd = find_window(cfg.general.window_title)
    if not hwnd:
        print("게임 창을 못 찾음"); return
    w = Calibrator(mode, Capture(), client_rect(hwnd), cfg, prof)
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    ka = QTimer(); ka.timeout.connect(lambda: None); ka.start(200)
    sys.exit(app.exec())


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode not in HINT:
        print(__doc__); sys.exit(1)
    main(mode)