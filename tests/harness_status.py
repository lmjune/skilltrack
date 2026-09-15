"""
상태창 검출/파싱 결과 시각화 + 시간 읽기.
사용법: python tests/harness_status.py tests/fixtures/status1.png 2880 1230 340 550
결과:   tests/out/<이름>_status.png  (고정 섹션=초록, 나머지=회색, 활성/비활성/시간 표시)
"""
import sys
from pathlib import Path
import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.rows import detect_rows
from core.status import parse_rows
from core.digits import GlyphLib, read_time

ROOT = Path(__file__).parent.parent
OUT = ROOT / "tests" / "out"
OUT.mkdir(exist_ok=True)


def run(image_path, rect):
    img = cv2.imread(image_path)
    x, y, w, h = rect
    crop = img[y:y + h, x:x + w]
    L = detect_rows(crop)
    if L is None:
        print("행 검출 실패"); return
    S = parse_rows(crop, L)
    lib = GlyphLib.load(ROOT / "assets" / "glyphs.json")
    pinned = set(L.sections[0]) if L.sections else set()

    print(f"pitch={L.pitch} 행={len(L.rows)} 섹션={[len(s) for s in L.sections]} (첫 섹션=고정)")
    vis = crop.copy()
    for s in S:
        r = L.rows[s.index]
        is_pin = s.index in pinned
        color = (0, 255, 0) if is_pin else (120, 120, 120)
        tx, ty, tw, th = r.text
        ix, iy, iw, ih = r.icon
        cv2.rectangle(vis, (ix - 1, iy - 1), (tx + tw, ty + th), color, 1)

        t = read_time(s.time_img, lib) if s.time_img is not None else None
        tstr = "-" if t is None else (f"{t.seconds}s" if t.seconds is not None else f"?{t.text}")
        tag = f"{'PIN' if is_pin else '   '} {'ON ' if s.active else 'off'} {'RED' if s.red else '   '} {tstr}"
        cv2.putText(vis, tag, (tx + tw + 6, ty + th - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
        print(f"  행{s.index:2d} {'고정' if is_pin else '    '} {'활성' if s.active else '비활성'} "
              f"{'빨강' if s.red else '    '} 시간={tstr}"
              + (f"  ⚠ 모르는 글자 {len(t.unknown)}개" if t and t.unknown else ""))

    out = OUT / (Path(image_path).stem + "_status.png")
    cv2.imwrite(str(out), cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    print("저장:", out)


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(__doc__); sys.exit(1)
    run(sys.argv[1], tuple(int(v) for v in sys.argv[2:6]))