"""
측정용 무손실 스냅샷 (dxcam 원본 픽셀. 앱/Qt/캘리브레이션과 무관).
UI 크기·글꼴 변형을 실측할 때 쓴다.

사용법:
  python win/snap.py 150_mabi
  python win/snap.py 150_mabi --rect 2910,1030,470,600

  인자 = 이 설정의 이름표 (저장 폴더 이름). 예: 100, 150_mabi, 150_nanum
  --rect x,y,w,h = F9 연속 저장 때 잘라 저장할 영역 (게임 화면 기준). 없으면 전체 화면을 저장

  F8 = 게임 화면 전체 한 장
  F9 = 연속 저장 시작/정지: 1초마다 한 장 (--rect 영역만), 최대 90장
  F7 = 종료
  (키 상태 폴링이라 게임 입력을 막지 않음)

저장 위치: tests/fixtures/variants/<이름표>/  (연속 저장은 burst_<시각>/ 하위 폴더)
"""
import argparse
import ctypes
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))
from win.capture import Capture
from win.window import find_window, client_rect

VK_F7, VK_F8, VK_F9 = 0x76, 0x77, 0x78
TITLE = "마비노기"
BURST_MAX = 90
BURST_INTERVAL = 1.0


def pressed(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def stamp():
    return f"{datetime.now():%Y%m%d_%H%M%S_%f}"[:-3]


def grab_client(cap):
    hwnd = find_window(TITLE)
    if not hwnd:
        print("게임 창을 못 찾음")
        return None
    cx, cy, cw, ch = client_rect(hwnd)
    try:
        return cap.grab_sure((cx, cy, cw, ch))
    except RuntimeError as e:
        print(f"캡처 실패: {e}")
        return None


def save(path, img):
    if path.suffix == ".webp":
        cv2.imwrite(str(path), img, [cv2.IMWRITE_WEBP_QUALITY, 101])     # 101 = 무손실 (PNG 보다 25~30% 작음)
    else:
        cv2.imwrite(str(path), img, [cv2.IMWRITE_PNG_COMPRESSION, 9])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?", default="untagged")
    ap.add_argument("--rect", default=None, help="x,y,w,h (게임 화면 기준)")
    a = ap.parse_args()
    rect = tuple(int(v) for v in a.rect.split(",")) if a.rect else None

    out = Path(__file__).parent.parent / "tests" / "fixtures" / "variants" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    cap = Capture()
    print(f"[{a.tag}] F8 = 전체 한 장, F9 = 연속 저장 시작/정지, F7 = 종료 → {out}")
    if rect:
        print(f"연속 저장 영역: {rect}")

    prev = {VK_F8: False, VK_F9: False}
    burst_dir, burst_n, burst_next = None, 0, 0.0
    while True:
        if pressed(VK_F7):
            break
        down = {k: pressed(k) for k in prev}
        edge = {k: down[k] and not prev[k] for k in prev}
        prev = down

        if edge[VK_F8]:
            frame = grab_client(cap)
            if frame is not None:
                p = out / f"{stamp()}.png"
                save(p, frame)
                print(f"저장 {p.name}  {frame.shape[1]}×{frame.shape[0]}")

        if edge[VK_F9]:
            if burst_dir is None:
                burst_dir = out / f"burst_{stamp()}"
                burst_dir.mkdir(parents=True, exist_ok=True)
                burst_n, burst_next = 0, time.time()
                frame = grab_client(cap)                 # 위치 확인용 전체 한 장
                if frame is not None:
                    save(burst_dir / "_full.png", frame)
                print(f"연속 저장 시작 → {burst_dir.name}")
            else:
                print(f"연속 저장 정지 ({burst_n}장)")
                burst_dir = None

        if burst_dir is not None and time.time() >= burst_next:
            burst_next += BURST_INTERVAL
            frame = grab_client(cap)
            if frame is not None:
                if rect:
                    x, y, w, h = rect
                    frame = frame[y:y + h, x:x + w]
                save(burst_dir / f"{stamp()}.webp", frame)     # 연속 저장은 무손실 WebP (용량)
                burst_n += 1
                if burst_n % 10 == 0:
                    print(f"  {burst_n}장")
                if burst_n >= BURST_MAX:
                    print(f"연속 저장 끝 ({burst_n}장)")
                    burst_dir = None

        time.sleep(0.02)


if __name__ == "__main__":
    main()
