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

GAP_MIN = 10        # 글자 덩어리를 나누는 빈 열 폭
TIME_GAP_MIN = 20   # 시간은 이름에서 이만큼 이상 떨어져 있어야 함


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
    name_range: tuple | None = None   # 텍스트 rect 안에서 이름의 (x0, x1)
    time_range: tuple | None = None   # 시간의 (x0, x1)

    @property
    def name_width(self):
        return (self.name_range[1] - self.name_range[0] + 1) if self.name_range else None


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

def _icon_fp(icon_bgr):
    g = cv2.cvtColor(icon_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = (g - g.min()) / (g.max() - g.min() + 1e-6)
    return fingerprint(g > 0.5, size=(16, 16))


def _row_strokes(text_bgr):
    """(이름용 마스크, 시간용 마스크, 활성 여부).
    이름: 흰 획이 있으면 흰색만(회색은 안티앨리어싱 노이즈), 없으면 회색 = 비활성. 이름은 빨개지지 않는다.
    시간: 흰색 또는 빨강."""
    white, gray, red = stroke_masks(text_bgr)
    n_white, n_gray = int(white.sum()), int(gray.sum())
    active = n_white >= max(8, n_gray * 0.5)
    name_mask = white | gray          # 활성/비활성 모두 같은 모양 (색만 다름)
    time_mask = white | gray | red
    return name_mask, time_mask, active, red


def _dense_runs(mask, runs, min_density=0.12):
    """글자 덩어리는 획 밀도가 높다 (영역의 20% 안팎). 물 반짝임 같은 잡음은 드문드문이라 버린다."""
    h = mask.shape[0]
    return [(a, b) for a, b in runs if mask[:, a:b + 1].sum() / (h * (b - a + 1)) >= min_density]


def _runs(mask, gap=GAP_MIN):
    """획 마스크의 열 분포를 덩어리로. [(x0, x1), ...]"""
    lit = np.where(mask.any(axis=0))[0]
    if len(lit) == 0:
        return []
    runs, start, prev = [], lit[0], lit[0]
    for c in lit[1:]:
        if c - prev > gap:
            runs.append((start, prev)); start = c
        prev = c
    runs.append((start, prev))
    return runs


def parse_rows(img, layout: RowLayout) -> list[RowState]:
    out = []
    for i, r in enumerate(layout.rows):
        x, y, w, h = r.text
        if layout.time_right is not None:          # 시간 끝 열을 알면 그 너머(패널 밖)는 보지 않음
            w = min(w, layout.time_right - x + 6)
        text = img[y:y + h, x:x + w]
        name_mask, time_mask, active, red = _row_strokes(text)

        name_runs = _dense_runs(name_mask, _runs(name_mask))
        time_runs = _dense_runs(time_mask, _runs(time_mask))

        # 시간: 오른쪽 끝 덩어리. 이름과 충분히 떨어져 있고(이름 안 띄어쓰기는 10px 이하) 폭이 시간답고,
        # 시간 끝 열(time_right)을 알면 거기서 끝나야 함 (오른쪽 정렬)
        time_rng = None
        if time_runs:
            ta, tb = time_runs[-1]
            prev_end = time_runs[-2][1] if len(time_runs) >= 2 else (name_runs[0][0] if name_runs else 0)
            aligned = layout.time_right is None or abs((x + tb) - layout.time_right) <= 3
            if aligned and ta - prev_end >= TIME_GAP_MIN and 12 <= (tb - ta) <= 80:
                time_rng = (ta, tb)

        # 이름: 첫 덩어리부터 시간 직전까지. 못 읽어도 행은 내보낸다
        # (밝은 배경의 반투명 글자는 세그멘테이션이 안 되지만, 행 번호로 추적하고 활성은 획 자리로 판정)
        if name_runs:
            a = name_runs[0][0]
            b = max([rr[1] for rr in name_runs if time_rng is None or rr[1] < time_rng[0]] or [a])
            name_img, nm, name_rng = text[:, a:b + 1], name_mask[:, a:b + 1], (a, b)
        else:
            name_img, nm, name_rng = text[:, :1], name_mask[:, :1], None

        time_img, is_red = None, False
        if time_rng:
            ta, tb = time_rng
            time_img = text[:, ta:tb + 1]
            is_red = int(red[:, ta:tb + 1].sum()) > int((time_mask & ~red)[:, ta:tb + 1].sum())

        ix, iy, iw, ih = r.icon
        out.append(RowState(
            index=i, name_fp=fingerprint(nm) if name_rng else b"",
            icon_fp=_icon_fp(img[iy:iy + ih, ix:ix + iw]),
            active=active, has_time=time_img is not None, red=is_red,
            name_img=name_img, time_img=time_img, name_range=name_rng, time_range=time_rng,
        ))
    return out