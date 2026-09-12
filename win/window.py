import ctypes
from ctypes import wintypes
import win32gui
import win32process

user32 = ctypes.windll.user32


def list_windows():
    """보이는 최상위 창 목록: [(hwnd, 제목, 프로세스명)]"""
    out = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            out.append((hwnd, win32gui.GetWindowText(hwnd), pid))
        return True

    win32gui.EnumWindows(cb, None)
    return out


def find_window(title_contains: str):
    """제목에 문자열이 포함된 첫 창의 hwnd. 대소문자 무시."""
    key = title_contains.lower()
    for hwnd, title, _ in list_windows():
        if key in title.lower():
            return hwnd
    return None


def client_rect(hwnd):
    """클라이언트 영역(테두리/제목표시줄 제외)의 화면 좌표 (x, y, w, h)"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (left, top))
    return (x, y, right - left, bottom - top)


if __name__ == "__main__":
    for hwnd, title, pid in list_windows():
        print(f"{hwnd:>10}  pid={pid:<6} {title}")
    hwnd = find_window("mabinogi") or find_window("마비노기")
    if hwnd:
        print("\n게임 창:", win32gui.GetWindowText(hwnd), "client rect:", client_rect(hwnd))