import time
import dxcam
import numpy as np


class Capture:
    """dxcam 래퍼. region은 화면 절대 좌표 (x, y, w, h)."""

    def __init__(self):
        self.cam = dxcam.create(output_color="BGR")

    def contains(self, x, y, w, h) -> bool:
        """영역이 캡처하는 모니터(주 모니터) 안에 다 들어가는가. dxcam 은 밖이면 ValueError 로 죽는다."""
        W, H = getattr(self.cam, "width", None), getattr(self.cam, "height", None)
        if not W or not H:
            return True
        return x >= 0 and y >= 0 and x + w <= W and y + h <= H

    def grab(self, region=None) -> np.ndarray | None:
        """region 없으면 전체 화면. 변화 없으면 None을 돌려줄 수 있음."""
        if region is None:
            return self.cam.grab()
        x, y, w, h = region
        return self.cam.grab(region=(x, y, x + w, y + h))

    def grab_sure(self, region=None, tries=10) -> np.ndarray:
        """None이 안 나올 때까지 재시도."""
        for _ in range(tries):
            f = self.grab(region)
            if f is not None:
                return f
            time.sleep(0.02)
        raise RuntimeError("캡처 실패")


if __name__ == "__main__":
    import sys
    import cv2
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from win.window import find_window, client_rect
    from core.grid import detect_grid_in

    hwnd = find_window("마비노기")
    cx, cy, cw, ch = client_rect(hwnd)
    print("client:", (cx, cy, cw, ch))

    cap = Capture()
    t = time.perf_counter()
    full = cap.grab_sure((cx, cy, cw, ch))
    print(f"전체 캡처 {full.shape} {1000*(time.perf_counter()-t):.1f}ms")
    cv2.imwrite("tests/out/live_full.png", full)

    # 스킬바 영역 (클라이언트 기준 상대 좌표)
    rect = (0, 0, 1230, 100)
    g = detect_grid_in(full, rect)
    print("격자:", None if g is None else f"{g.cols}x{g.rows} {g.w}x{g.h}")

    # 슬롯 영역만 반복 캡처 속도 측정
    bar = (cx, cy, 1230, 110)
    t = time.perf_counter(); n = 30
    for _ in range(n):
        cap.grab_sure(bar)
    print(f"영역 캡처 {n}회 평균 {1000*(time.perf_counter()-t)/n:.1f}ms")