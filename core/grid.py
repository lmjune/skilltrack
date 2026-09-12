from dataclasses import dataclass
import cv2
import numpy as np


@dataclass
class Grid:
    """슬롯 위치를 명시적으로 들고 있는 격자. 균일 격자든 그룹 격자든 표현 가능."""
    xs: list[int]   # 각 열의 시작 x
    ys: list[int]   # 각 행의 시작 y
    w: int          # 슬롯 폭
    h: int          # 슬롯 높이

    @property
    def cols(self): return len(self.xs)
    @property
    def rows(self): return len(self.ys)

    def slot_rect(self, col, row):
        return (self.xs[col], self.ys[row], self.w, self.h)

    def all_slots(self):
        for r in range(self.rows):
            for c in range(self.cols):
                yield (r * self.cols + c, self.slot_rect(c, r))


# ---------------------------------------------------------------- 내부 함수

def _signed_profile(gray, axis):
    """부호 있는 그래디언트 합. axis=0 → x 프로파일, axis=1 → y 프로파일.
    슬롯 시작(어두움→밝음)은 양수 피크, 슬롯 끝(밝음→어두움)은 음수 피크."""
    dx, dy = (1, 0) if axis == 0 else (0, 1)
    return cv2.Sobel(gray, cv2.CV_32F, dx, dy, ksize=3).sum(axis=axis)


def _peaks(p, thr):
    """thr 이상인 국소 최대 → (위치, 세기)"""
    return [(i, float(p[i])) for i in range(1, len(p) - 1)
            if p[i] > thr and p[i] >= p[i - 1] and p[i] >= p[i + 1]]


def _edges(profile, k=0.2):
    thr = np.abs(profile).max() * k
    rising = _peaks(profile, thr)
    falling = [(i, s) for i, s in _peaks(-profile, thr)]
    return rising, falling


def _pitch_by_autocorr(profile, min_size, max_size):
    """부호 프로파일 자기상관의 첫 양수 최대 = 슬롯 간격(pitch). 그룹 틈이 있어도 안정적."""
    p = profile - profile.mean()
    a = np.correlate(p, p, "full")[len(p) - 1:]
    a = a / (a[0] + 1e-9)
    hi = min(max_size, len(a) - 1)
    if hi <= min_size:
        return None
    pitch = int(np.argmax(a[min_size:hi])) + min_size
    return pitch if a[pitch] >= 0.1 else None


def _find_slots(profile, min_size, max_size, debug=None):
    """pitch를 자기상관으로 구한 뒤, r + ~0.9·pitch 근처에 하강 피크가 있는 상승 피크 r 를 슬롯으로."""
    pitch = _pitch_by_autocorr(profile, min_size, max_size)
    if pitch is None:
        return [], None, None
    size = int(round(pitch * 0.9))   # 대략값. 정확한 폭은 이후 스냅에서 실측
    tol = 0.2
    rising, falling = _edges(profile)
    if not rising or not falling:
        return [], None, None
    fpos = np.array([f for f, _ in falling])
    fstr = {f: s for f, s in falling}

    lo, hi = size * (1 - tol), size * (1 + tol)
    cands = []
    for r, sr in rising:
        partners = [fstr[int(f)] for f in fpos if lo <= f - r <= hi]
        if partners:
            cands.append((sr + max(partners), r))
    cands.sort(reverse=True)
    accepted = []
    for _, r in cands:
        if all(abs(r - x) >= size * 0.85 for x in accepted):
            accepted.append(r)
    accepted = sorted(accepted)
    if debug is not None:
        debug.update(rising=rising, falling=falling, size=size)
    return accepted, size, pitch


def _snap(gray, starts, pitch, axis, band, dark_ratio=0.35):
    """각 슬롯을 테두리 선에 정밀히 맞춘다.
    1) 끝 테두리: [s+0.75·pitch, s+pitch) 에서 가장 왼쪽 어두운 선
    2) 시작: 끝에서 pitch 만큼 왼쪽 구간 [eb-pitch+1, eb-0.6·pitch] 에서 가장 오른쪽 어두운 선 + 1
    '어두운 선' = 밴드의 상위 25% 밝기가 낮은 열(밴드 중앙값의 절반 이하). 진짜 테두리는 모든 행에서 어둡고,
    아이콘 내부의 검은 부분은 프레임 행에서 밝아 걸러진다. 구분선이 여러 겹이어도 안쪽 선을 잡는다."""
    b0, b1 = band
    seg = gray[b0:b1, :] if axis == 0 else gray[:, b0:b1].T
    prof = np.percentile(seg, 75, axis=0)
    n = len(prof)
    abs_dark = np.median(prof) * 0.5     # 밴드 전체 기준으로도 확실히 어두워야 함
    black_thr = max(12.0, np.median(prof) * 0.25)   # '진짜 테두리' = 거의 검정

    def blacks(lo, hi):
        lo, hi = max(0, lo), min(n, hi)
        return [i for i in range(lo, hi) if prof[i] <= black_thr]

    def darks(lo, hi):
        lo, hi = max(0, lo), min(n, hi)
        if hi - lo < 2:
            return []
        w = prof[lo:hi]
        thr = min(w.min() + (w.max() - w.min()) * dark_ratio, abs_dark)
        return [i for i in range(lo, hi) if prof[i] <= thr]

    # 1차: 끝 테두리 확정, 시작은 가장 안쪽 어두운 선 → 크기 중앙값
    ends, first, sizes = [], [], []
    for s in starts:
        d = darks(s + int(pitch * 0.75), s + pitch)
        eb = min(d) if d else s + int(pitch * 0.9)
        d = darks(eb - pitch + 1, eb - int(pitch * 0.6) + 1)
        ns = (max(d) + 1) if d else s
        ends.append(eb); first.append(ns); sizes.append(eb - ns)
    size = int(np.median(sizes))

    # 2차: 시작 후보 c (어두운 선) 중 c+1+size 에도 어두운 선이 있는 것만 유효.
    #      유효 후보 중 검출기 위치 s 에 가장 가까운 것. (검은 아이콘 내부 선은 짝이 없어 탈락,
    #      겹겹 구분선은 짝이 맞는 안쪽 선이 선택됨)
    new_starts = []
    for s, ns in zip(starts, first):
        cands = blacks(s - 6, s + int(pitch * 0.4))
        valid = [c for c in cands if blacks(c + size - 1, c + size + 3)]
        pick = min(valid, key=lambda c: abs(c + 1 - s)) if valid else None
        new_starts.append(pick + 1 if pick is not None else ns)
    return new_starts, size


def _keep_overlapping(starts, size, lo, hi, min_overlap):
    """[lo, hi) 구간과 size*min_overlap 이상 겹치는 슬롯만."""
    return [s for s in starts if min(s + size, hi) - max(s, lo) >= size * min_overlap]


def _chain_extend(all_starts, kept, size, factor=2.0):
    """kept 슬롯과 간격 factor*size 이내로 이어진 이웃 슬롯까지 포함한 연속 구간.
    정제 밴드용: 바로 옆 행/열은 문맥으로 쓰되, 멀리 떨어진 가짜는 끊는다."""
    if not kept:
        return []
    keep = set(kept)
    changed = True
    while changed:
        changed = False
        for s in all_starts:
            if s in keep:
                continue
            if any(abs(s - k) <= size * factor for k in keep):
                keep.add(s); changed = True
    return sorted(keep)


def detect_grid(img, focus=None, min_size=16, max_size=120, min_overlap=0.5, debug=None):
    """
    img 안에서 슬롯 격자를 찾는다.
    focus: (x, y, w, h) — 유저가 실제로 드래그한 영역(img 좌표). 최종 결과는 이 영역과
           겹치는 슬롯만. 정제 단계에서는 focus에 이어진 이웃 슬롯까지 문맥으로 사용.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = gray.shape
    fx, fy, fw, fh = focus if focus else (0, 0, W, H)

    # 1차: 열
    xs_all, sw, px = _find_slots(_signed_profile(gray, 0), min_size, max_size)
    if not xs_all:
        return None
    xs = _keep_overlapping(xs_all, sw, fx, fx + fw, min_overlap)
    if not xs:
        return None
    band_x = _chain_extend(xs_all, xs, sw)

    # 2차: 열 밴드 안에서 행
    x0, x1 = max(0, band_x[0] - 2), min(W, band_x[-1] + sw + 2)
    ys_all, sh, py = _find_slots(_signed_profile(gray[:, x0:x1], 1), min_size, max_size)
    if not ys_all:
        return None
    ys = _keep_overlapping(ys_all, sh, fy, fy + fh, min_overlap)
    if not ys:
        return None
    band_y = _chain_extend(ys_all, ys, sh)

    # 3차: 행 밴드 안에서 열 재검출 (정제)
    y0, y1 = max(0, band_y[0] - 2), min(H, band_y[-1] + sh + 2)
    xs2_all, sw2, px2 = _find_slots(_signed_profile(gray[y0:y1, :], 0), min_size, max_size)
    if xs2_all:
        xs2 = _keep_overlapping(xs2_all, sw2, fx, fx + fw, min_overlap)
        if xs2:
            xs_all, xs, sw, px = xs2_all, xs2, sw2, px2

    # 검증: 아이콘은 정사각형에 가깝고, 실제 격자라면 주변에 슬롯이 여럿 있다
    if not (0.75 <= sw / sh <= 1.33):
        return None
    if len(xs_all) * len(ys_all) < 3:
        return None

    # 테두리 선에 정밀 스냅
    # 테두리 선에 정밀 스냅. 폭/높이는 이웃 슬롯 전체의 중앙값으로 (슬롯 하나만 골라도 안정적)
    band_x = _chain_extend(xs_all, xs, sw)
    snapped_x, sw2 = _snap(gray, band_x, px, 0, (band_y[0], band_y[-1] + sh))
    snapped_y, sh2 = _snap(gray, band_y, py, 1, (band_x[0], band_x[-1] + sw))
    xs = [nx for ox, nx in zip(band_x, snapped_x) if ox in xs]
    ys = [ny for oy, ny in zip(band_y, snapped_y) if oy in ys]
    if 0.7 * sw <= sw2 <= 1.25 * sw: sw = sw2
    if 0.7 * sh <= sh2 <= 1.25 * sh: sh = sh2

    if debug is not None:
        debug.update(sw=sw, sh=sh, xs_all=xs_all, ys_all=ys_all)
    return Grid(xs=xs, ys=ys, w=sw, h=sh)


def detect_grid_in(full_img, rect, margin=0.3, min_margin_px=120, min_overlap=0.5):
    """유저가 드래그한 rect를 여유 있게 확장해 검출. 반환 좌표는 full_img 기준."""
    H, W = full_img.shape[:2]
    x, y, w, h = rect
    mx, my = max(int(w * margin), min_margin_px), max(int(h * margin), min_margin_px)
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1, y1 = min(W, x + w + mx), min(H, y + h + my)

    g = detect_grid(full_img[y0:y1, x0:x1], focus=(x - x0, y - y0, w, h), min_overlap=min_overlap)
    if g is None:
        return None
    return Grid(xs=[x0 + sx for sx in g.xs], ys=[y0 + sy for sy in g.ys], w=g.w, h=g.h)