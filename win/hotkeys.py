"""
전역 단축키 (키 상태 폴링). 문자열 형식: "F9", "Ctrl+Shift+F9", "Alt+Q", "Ctrl+Alt+Home"
키를 가로채지 않으므로 게임에도 그대로 들어간다 → 게임이 안 쓰는 키를 고를 것.

    hk = Hotkeys(app)
    hk.bind("Ctrl+F9", callback)
    hk.rebind_all({"toggle": ("F9", cb1), ...})
"""
import ctypes

import time

from PySide6.QtCore import QObject, QTimer

user32 = ctypes.windll.user32
MOD = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
VK = {**{f"f{i}": 0x6F + i for i in range(1, 25)},
      **{c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
      "space": 0x20, "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22,
      "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "pause": 0x13, "scrolllock": 0x91, "numlock": 0x90,
      "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "backspace": 0x08, "enter": 0x0D, "return": 0x0D,
      **{f"num{i}": 0x60 + i for i in range(10)}, "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\\\": 0xDC,
      ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF}


def parse(text: str):
    """'Ctrl+Shift+F9' → (modifiers, vk). 잘못되면 ValueError."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("빈 단축키")
    mods, key = 0, None
    for p in parts:
        if p in MOD:
            mods |= MOD[p]
        elif key is None:
            key = VK.get(p, VK.get(p.upper()))
            if key is None:
                raise ValueError(f"모르는 키: {p}")
        else:
            raise ValueError("키는 하나만")
    if key is None:
        raise ValueError("키가 없음 (조합키만 있음)")
    return mods, key


MOD_VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}


class Hotkeys(QObject):
    """키 상태 폴링(GetAsyncKeyState). 훅도, 키 가로채기도 없다 — 게임에도 키가 그대로 들어간다.
    기본은 꺼져 있고(enabled=False) 일반 설정에서 켠다."""

    def __init__(self, app, poll_ms=50):
        super().__init__()
        self._cbs, self._next = {}, 1
        self._combos = {}            # hid → (mods, vk)
        self._down = set()
        self._poll = QTimer(self); self._poll.timeout.connect(self._poll_keys)
        self.enabled = False
        self.poll_ms = poll_ms

    def set_enabled(self, on: bool):
        self.enabled = bool(on)
        if self.enabled and self._combos:
            self._poll.start(self.poll_ms)
        else:
            self._poll.stop(); self._down.clear()

    def _poll_keys(self):
        for hid, (mods, vk) in self._combos.items():
            pressed = user32.GetAsyncKeyState(vk) & 0x8000
            for name, bit in MOD.items():
                if mods & bit:
                    pressed = pressed and (user32.GetAsyncKeyState(MOD_VK[name]) & 0x8000)
            if pressed and hid not in self._down:
                self._down.add(hid)
                cb = self._cbs.get(hid)
                if cb:
                    cb()
            elif not pressed:
                self._down.discard(hid)

    def bind(self, text: str, cb) -> int:
        mods, vk = parse(text)
        hid = self._next; self._next += 1
        self._cbs[hid] = cb; self._combos[hid] = (mods, vk)
        return hid

    def unbind_all(self):
        self._cbs.clear(); self._combos.clear(); self._down.clear(); self._poll.stop()

    def rebind_all(self, table: dict) -> list[str]:
        """table: {이름: (문자열, 콜백)} → 잘못된 문자열 목록"""
        self.unbind_all()
        failed = []
        for name, (text, cb) in table.items():
            if not text:
                continue
            try:
                self.bind(text, cb)
            except ValueError as e:
                failed.append(f"{name}: '{text}' — {e}")
        self.set_enabled(self.enabled)
        return failed