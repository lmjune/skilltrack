"""
스크린샷 + 드래그 rect → 격자 검출 결과 시각화.
사용법: python tests/harness.py tests/fixtures/screen1.png x y w h
결과:   tests/out/<이름>_grid.png (검출 슬롯 초록 박스 + 번호, 유저 rect 빨강)
"""
import sys
from pathlib import Path
import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.grid import detect_grid_in

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def run(image_path: str, rect: tuple[int, int, int, int], zoom: int = 2):
    img = cv2.imread(image_path)
    if img is None:
        print(f"이미지 로드 실패: {image_path}")
        return
    x, y, w, h = rect
    grid = detect_grid_in(img, rect)

    vis = img.copy()
    cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 1)
    if grid is None:
        print("격자 검출 실패")
    else:
        print(f"검출: {grid.cols}x{grid.rows}, 슬롯 {grid.w}x{grid.h}")
        print(f"  xs={grid.xs}")
        print(f"  ys={grid.ys}")
        for idx, (sx, sy, sw, sh) in grid.all_slots():
            cv2.rectangle(vis, (sx - 1, sy - 1), (sx + sw, sy + sh), (0, 255, 0), 1)  # 테두리 선 위에
            cv2.putText(vis, str(idx), (sx + 2, sy + 11),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 255), 1)

    pad = 40
    crop = vis[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    crop = cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    out_path = OUT / (Path(image_path).stem + "_grid.png")
    cv2.imwrite(str(out_path), crop)
    print(f"저장: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(__doc__)
        sys.exit(1)
    run(sys.argv[1], tuple(int(v) for v in sys.argv[2:6]))