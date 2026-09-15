"""
상태(버프) 목록창 행 검출.  ── 배경 무관 버전

구조 가정:
  [아이콘 박스][이름 텍스트 ............ 시간 텍스트]
  행이 일정 간격(pitch)으로 세로 나열. 섹션 구분(간격이 벌어짐)이 있을 수 있음.

패널이 반투명이라 절대 밝기는 배경에 따라 뒤집힌다 (어두운 맵: 아이콘이 밝음, 눈밭: 아이콘이 어두움).
그래서 밝기 대신 **엣지 에너지(질감)** 만 쓴다. 아이콘은 어느 배경에서든 질감이 있고, 행 사이 틈은 평평하다.
"""
from dataclasses import dataclass, field
import cv2
import numpy as np

from core.strokes import any_stroke


@dataclass
class Row:
    y: int
    icon: tuple
    text: tuple


@dataclass
class RowLayout:
    pitch: int
    icon_x: int
    icon_w: int
    icon_h: int
    text_x: int
    right: int
    rows: list[Row] = field(default_factory=list)
    sections: list[list[int]] = field(default_factory=list)

    @property
    def pinned(self) -> list[Row]:
        """첫 번째 섹션 = 게임에서 고정한 버프들. 감시 대상은 여기서만 고른다."""
        return [self.rows[i] for i in self.sections[0]] if self.sections else []


def _edge(gray):
    return (np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
            + np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)))


def _vertical_segments_per_col(gray, pct=90, lo=8, hi=30):
    """열마다 '아이콘 높이 정도(lo~hi px)로 끊어진 세로 엣지 선분'의 개수.
    아이콘 열은 행마다 질감이 있어 행 수만큼 나오고, 배경의 긴 세로선은 안 끊겨서 0~1,
    글자 열은 획이 짧고 행마다 위치가 달라 적게 나온다."""
    sx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    b = sx > np.percentile(sx, pct)
    H, W = b.shape
    pad = np.zeros((1, W), bool)
    d = np.diff(np.vstack([pad, b, pad]).astype(np.int8), axis=0)   # +1 시작, -1 끝
    counts = np.zeros(W, int)
    for x in range(W):
        starts = np.where(d[:, x] == 1)[0]
        ends = np.where(d[:, x] == -1)[0]
        lens = ends - starts
        counts[x] = int(((lens >= lo) & (lens <= hi)).sum())
    return counts


def _icon_band_candidates(gray, min_w=8, max_w=24, dip_tol=4):
    """세로 선분 수가 최댓값의 50% 이상인 열들의 연속 구간들 (왼쪽부터). 각 후보는 이후 검증을 거친다."""
    runs = _vertical_segments_per_col(gray)
    if runs.max() < 3:
        return []
    thr = runs.max() * 0.5
    W = len(runs)
    out, x = [], 0
    while x < W:
        if runs[x] < thr:
            x += 1; continue
        L = x; dip = 0; R = x
        while x < W:
            if runs[x] >= thr:
                R = x; dip = 0
            else:
                dip += 1
                if dip > dip_tol:
                    break
            x += 1
        width = R - L + 1
        if width > max_w:
            cut = L + min_w + int(np.argmin(runs[L + min_w:L + max_w]))
            R, width = cut - 1, cut - L
        if min_w <= width <= max_w:
            out.append((L, R + 1))
        x = R + 1
    return out


def _pitch(profile, lo=12, hi=64):
    p = profile - profile.mean()
    a = np.correlate(p, p, "full")[len(p) - 1:]
    a = a / (a[0] + 1e-9)
    hi = min(hi, len(a) - 1)
    if hi <= lo:
        return None
    k = int(np.argmax(a[lo:hi])) + lo
    return k if a[k] > 0.15 else None


def _box_tops(profile, box_h, pitch):
    """'박스 안 평균 - 박스 위아래 평균'이 큰 y (엣지 프로파일)."""
    n = len(profile)
    pad = max(2, (pitch - box_h) // 2)
    score = np.full(n, -1e9, dtype=np.float32)
    for y in range(pad, n - box_h - pad):
        inside = profile[y:y + box_h].mean()
        outside = np.concatenate([profile[y - pad:y], profile[y + box_h:y + box_h + pad]]).mean()
        score[y] = inside - outside
    thr = max(score.max() * 0.25, 1)
    cands = sorted(((score[y], y) for y in range(1, n - 1)
                    if score[y] > thr and score[y] >= score[y - 1] and score[y] >= score[y + 1]),
                   reverse=True)
    tops = []
    for _, y in cands:
        if all(abs(y - t) >= pitch * 0.7 for t in tops):
            tops.append(y)
    return sorted(tops)


def _icon_height(profile, tops, pitch):
    """상단 → 엣지가 배경 수준으로 떨어지는 지점까지의 중앙값."""
    hs = []
    for t in tops:
        seg = profile[t + 4:t + pitch]
        if len(seg) < 4:
            continue
        base = profile[t:t + 4].mean()
        for i, v in enumerate(seg):
            if v < base * 0.2:
                hs.append(i + 4); break
    return int(np.median(hs)) if hs else max(8, pitch - 8)


def _text_centers(edge, x0, x1, icon_h, pitch):
    e = edge[:, x0:x1].mean(axis=1)
    k = max(3, icon_h)
    s = np.convolve(e, np.ones(k) / k, mode="same")
    thr = s.max() * 0.15
    peaks = [y for y in range(1, len(s) - 1) if s[y] > thr and s[y] >= s[y - 1] and s[y] >= s[y + 1]]
    keep = []
    for y in peaks:
        if keep and y - keep[-1] < pitch * 0.7:
            if s[y] > s[keep[-1]]:
                keep[-1] = y
        else:
            keep.append(y)
    return keep, s


def _fill_regular(tops, pitch, evidence, weak):
    out = [tops[0]] if tops else []
    for a, b in zip(tops, tops[1:]):
        k = round((b - a) / pitch)
        if k >= 2 and abs((b - a) - k * pitch) <= pitch * 0.15:
            for i in range(1, k):
                y = int(round(a + i * (b - a) / k))
                if evidence[y:y + pitch // 2].max() > weak:
                    out.append(y)
        out.append(b)
    return out


def _refine_band(gray, band, min_w=8):
    """띠의 좌우 끝을 프레임 선(세로 엣지 열 피크)에 맞춘다. 선분 수 기준 띠는 몇 px 넘칠 수 있다."""
    L, R = band
    sx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0)
    seg = sx[L:R]
    peaks = [i for i in range(1, len(seg) - 1) if seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]]
    if not peaks:
        return band
    strong = [i for i in peaks if seg[i] >= seg[peaks].max() * 0.5]
    left = min(strong)
    rights = [i for i in strong if i - left >= min_w]
    right = max(rights) if rights else max(strong)
    return (L + left, L + right + 1)


def _detect_with_band(gray, edge, strokes, band, debug=None):
    H, W = gray.shape
    ix0, ix1 = _refine_band(gray, band)
    prof = edge[:, ix0:ix1].mean(axis=1)

    pitch = _pitch(prof)
    if pitch is None:
        return None
    icon_h = _icon_height(prof, _box_tops(prof, max(8, pitch - 8), pitch), pitch)

    # 아이콘은 정사각형 → 띠의 오른쪽 끝을 icon_h 로 고정 (선분 수 기준 띠는 오른쪽으로 넘칠 수 있음)
    ix1 = min(ix1, ix0 + icon_h + 1)
    text_x = ix1 + 1
    if text_x >= W - 10:
        return None
    lit = np.where(strokes[:, text_x:].any(axis=0))[0]
    right = min(W, text_x + int(lit[-1]) + 4) if len(lit) else W

    tops_a = _box_tops(prof, icon_h, pitch)
    centers, energy = _text_centers(edge, text_x, right, icon_h, pitch)
    tops_b = [c - icon_h // 2 for c in centers]

    def icon_energy(t):
        return prof[max(0, t):t + icon_h].mean()

    ref = np.median([icon_energy(t) for t in tops_a]) if tops_a else prof.mean() * 3

    def has_icon(t):
        return icon_energy(t) > ref * 0.15

    tops = list(tops_a)
    for t in tops_b:
        if not any(abs(a - t) < pitch * 0.5 for a in tops_a) and has_icon(t):
            tops.append(t)
    tops = sorted(t for t in tops if 0 <= t <= H - icon_h)
    if not tops:
        return None
    tops = _fill_regular(tops, pitch, energy, weak=energy.max() * 0.04)
    tops = [t for t in tops if has_icon(t)]

    # 모든 행에는 이름 글자가 있다. 획이 거의 없는 행(패널 테두리 등)은 버림
    def has_name(t):
        return int(strokes[t:t + icon_h, text_x:right].sum()) >= 10

    tops = [t for t in tops if has_name(t)]

    # 이웃과 2·pitch 이상 떨어진 외톨이 행은 목록의 일부가 아님 (패널 위아래의 다른 UI)
    if len(tops) >= 2:
        keep = []
        for i, t in enumerate(tops):
            d = min(abs(t - tops[j]) for j in (i - 1, i + 1) if 0 <= j < len(tops))
            if d <= pitch * 2:
                keep.append(t)
        tops = keep

    # 검증: 행 간격 대부분이 pitch, 아이콘은 정사각형에 가까움, 아이콘 사이 틈은 평평
    if len(tops) < 2:
        return None
    gaps = np.diff(tops)
    if (np.abs(gaps - pitch) <= 1).sum() < 0.6 * len(gaps):
        return None
    iw = ix1 - ix0
    if not (0.6 <= iw / icon_h <= 1.7) or icon_h < pitch * 0.4:
        return None
    icon_e = np.median([prof[t:t + icon_h].mean() for t in tops])
    gap_e = np.median([prof[t + icon_h:t + pitch].mean() for t in tops[:-1]]) if len(tops) > 1 else 0
    if gap_e > icon_e * 0.35:
        return None

    rows = [Row(y=t, icon=(ix0, t, ix1 - ix0, icon_h),
                text=(text_x, t, right - text_x, icon_h)) for t in tops]
    sections, cur = [], [0]
    for i in range(1, len(tops)):
        if tops[i] - tops[i - 1] > pitch * 1.25:
            sections.append(cur); cur = []
        cur.append(i)
    sections.append(cur)

    if debug is not None:
        debug.update(prof=prof, band=band, tops_a=tops_a, tops_b=tops_b, energy=energy)
    return RowLayout(pitch=pitch, icon_x=ix0, icon_w=ix1 - ix0, icon_h=icon_h,
                     text_x=text_x, right=right, rows=rows, sections=sections)


def detect_rows(img, debug=None) -> RowLayout | None:
    """아이콘 열 후보를 왼쪽부터 시도해서 검증을 통과하는 첫 레이아웃."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    edge = _edge(gray)
    strokes = any_stroke(img)
    for band in _icon_band_candidates(gray):
        L = _detect_with_band(gray, edge, strokes, band, debug)
        if L is not None:
            return L
    return None