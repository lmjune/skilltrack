"""
상태창 각 행의 내용 읽기.  ── 배경 무관 버전

행 = [아이콘][이름 텍스트 ........ 시간 텍스트(오른쪽 정렬, 없을 수 있음)]

패널이 반투명이라 배경 밝기를 믿을 수 없다. 대신 게임이 글자를 그리는 방식을 이용한다:
  - 획은 흰색(활성) / 회색 127(비활성) / 빨강(1분 미만 시간). 배경과 무관한 고정 색.
  - 획 둘레에 항상 검은 외곽선이 있다.
그래서 '획 색이면서 근처에 어두운 픽셀이 있는 것'만 획으로 본다. 밝은 눈밭 배경도 외곽선이 없으니 제외된다.

- 식별: 이름 획 마스크 지문 (고정 폰트라 같은 버프는 픽셀까지 같다). 아이콘 지문은 보조.
- 활성 여부: 이름 획이 흰색 vs 회색 중 어느 쪽이 많은가
- 시간: 획 유무, 빨강 여부
"""
from dataclasses import dataclass
import cv2
import numpy as np

from core.rows import RowLayout
from core.strokes import stroke_masks

GAP_MIN = 10   # 이름과 시간 사이 최소 빈 열 폭


@dataclass
class RowState:
    index: int
    name_fp: bytes
    icon_fp: bytes
    active: bool
    has_time: bool
    red: bool
    name_img: np.ndarray
    time_img: np.ndarray | None


# ---------------------------------------------------------------- 지문

def _bbox(mask):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return mask
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def fingerprint(mask: np.ndarray, size=(64, 8)) -> bytes:
    """불리언 마스크 → 바운딩 박스로 자름(위치 무관) → 고정 크기로 축소 → 평균 이상 = 1."""
    small = cv2.resize(_bbox(mask).astype(np.float32), size, interpolation=cv2.INTER_AREA)
    bits = (small > max(small.mean(), 1e-3)).ravel()
    return np.packbits(bits).tobytes()


def fp_distance(a: bytes, b: bytes) -> float:
    if len(a) != len(b):
        return 1.0
    x = np.bitwise_xor(np.frombuffer(a, np.uint8), np.frombuffer(b, np.uint8))
    return int(np.unpackbits(x).sum()) / (len(a) * 8)


def fp_same(a: bytes, b: bytes, thr=0.10) -> bool:
    return fp_distance(a, b) <= thr


# ---------------------------------------------------------------- 파싱

def _split_name_time(mask):
    """획 마스크의 열 분포로 이름/시간 범위를 나눈다. 오른쪽 끝 덩어리가 GAP_MIN 이상 떨어져 있으면 시간."""
    lit = np.where(mask.any(axis=0))[0]
    if len(lit) == 0:
        return None, None
    runs, start, prev = [], lit[0], lit[0]
    for c in lit[1:]:
        if c - prev > GAP_MIN:
            runs.append((start, prev)); start = c
        prev = c
    runs.append((start, prev))
    if len(runs) >= 2:
        return (runs[0][0], runs[-2][1]), runs[-1]
    return runs[0], None


def _icon_fp(icon_bgr):
    g = cv2.cvtColor(icon_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = (g - g.min()) / (g.max() - g.min() + 1e-6)
    return fingerprint(g > 0.5, size=(16, 16))


def _row_strokes(text_bgr):
    """(획 마스크, 활성 여부). 흰 획이 있으면 흰색만(회색은 안티앨리어싱 노이즈), 없으면 회색 = 비활성."""
    white, gray, red = stroke_masks(text_bgr)
    n_white, n_gray = int(white.sum()), int(gray.sum())
    active = n_white >= max(8, n_gray * 0.5)
    strokes = (white | red) if active else (gray | red)
    return strokes, active, red


def parse_rows(img, layout: RowLayout) -> list[RowState]:
    out = []
    for i, r in enumerate(layout.rows):
        x, y, w, h = r.text
        text = img[y:y + h, x:x + w]
        strokes, active, red = _row_strokes(text)
        name_rng, time_rng = _split_name_time(strokes)
        if name_rng is None:
            continue
        a, b = name_rng
        name_img, name_mask = text[:, a:b + 1], strokes[:, a:b + 1]

        time_img, is_red = None, False
        if time_rng:
            ta, tb = time_rng
            time_img = text[:, ta:tb + 1]
            is_red = int(red[:, ta:tb + 1].sum()) > int((strokes & ~red)[:, ta:tb + 1].sum())

        ix, iy, iw, ih = r.icon
        out.append(RowState(
            index=i,
            name_fp=fingerprint(name_mask),
            icon_fp=_icon_fp(img[iy:iy + ih, ix:ix + iw]),
            active=active,
            has_time=time_img is not None,
            red=is_red,
            name_img=name_img, time_img=time_img,
        ))
    return out