"""
시간 텍스트 ("1분 55초", "43초") 읽기.

게임 폰트가 고정이라 OCR 대신 글자 모양을 그대로 외운다.
- 글자 분리: 빈 열 기준
- 인식: 저장된 글자 마스크와 거의 일치하는 것 (몇 픽셀 차이 허용)
- 모르는 글자: None 반환 + unknown 목록에 담아 나중에 라벨링

라이브러리(assets/glyphs.json)는 알고 있는 문자열로 부트스트랩하고, 부족한 글자(7, 8, 9 등)는
실사용 중 모르는 글자가 나올 때 채운다.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
import numpy as np

MAX_DIFF = 1        # 같은 글자로 볼 최대 픽셀 차이 (렌더링이 픽셀 단위로 정확하다. 3이면 9↔3 혼동)

# 안티앨리어싱 글꼴 (UI 150%): 같은 글자도 찍히는 위치에 따라 가장자리가 1~2px 달라진다.
# → 글자마다 여러 모양을 템플릿으로 두고, ±1px 어긋남을 허용한 픽셀 차이로 가장 가까운 것.
#   실측 (150% 두 글꼴, 글자 900여 개): 같은 글자끼리 최대 8, 다른 글자끼리 최소 11 (마비옛체 3↔9)
FUZZY_MAX = 9       # 이 차이 이하일 때만 인정 (큰 글자는 픽셀 수의 FUZZY_REL 까지: '분' 은 획이 많아 차이도 크다)
FUZZY_REL = 0.2
FUZZY_MARGIN = 2    # 다른 글자 중 가장 가까운 것보다 이만큼은 가까워야 인정 (애매하면 모름)
# 처음 보는 위치의 글자 (예: 분 자리 '2')는 차이가 좀 더 클 수 있다. 그래도 다른 글자보다 확실히(2배) 가까우면 인정.
# 실측: 맞는 답의 (두 번째로 가까운 다른 글자 / 가장 가까운 거리) 최소 2.38, 다른 글자끼리 최소 차이 11
FUZZY_FAR_REL = 0.4     # 픽셀 수 대비 이 비율까지
FUZZY_FAR_RATIO = 2.0   # 두 번째 후보가 이 배수 이상 멀 때


@dataclass
class Glyph:
    x0: int
    x1: int
    mask: np.ndarray    # bool (h, w) — 행 방향은 bbox 로 잘라냄
    label: str | None = None


@dataclass
class TimeRead:
    seconds: int | None
    text: str
    unknown: list[Glyph] = field(default_factory=list)
    plausible: bool = True     # 시간 텍스트처럼 생겼는가 (마지막 글자가 초/분). 아니면 배경 잡음


def _to_mask(img_bgr) -> np.ndarray:
    from core.strokes import stroke_masks
    from core import screen
    w, g, r = stroke_masks(img_bgr)
    if screen.current().fuzzy:
        # 안티앨리어싱 글꼴: 흰 글자는 ≥250 인 '거의 다 덮인' 픽셀만 남는데, 빨강 규칙(r≥190)은 가장자리까지 넣어
        # 같은 글자가 더 굵어진다. 빨강도 거의 다 덮인 픽셀만 → 흰 글자와 같은 모양이 되어 템플릿을 같이 쓴다
        rr = img_bgr[:, :, 2].astype(np.int16)
        r = r & (rr >= 255)          # 흰 글자와 같은 기준 (완전히 덮인 픽셀)
    return w | r      # 시간 글자는 흰색 아니면 빨강 (비활성 회색 없음)


def segment(time_img) -> list[Glyph]:
    m = _to_mask(time_img)
    cols = m.any(axis=0)
    glyphs, start = [], None
    for x, b in enumerate(cols):
        if b and start is None:
            start = x
        elif not b and start is not None:
            glyphs.append((start, x)); start = None
    if start is not None:
        glyphs.append((start, len(cols)))
    out = []
    for a, b in glyphs:
        sub = m[:, a:b]
        rows = np.where(sub.any(axis=1))[0]
        out.append(Glyph(a, b, sub[rows[0]:rows[-1] + 1]))
    return out


def _pad(m, H, W, dy=0, dx=0):
    c = np.zeros((H + 2, W + 2), bool)
    c[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]] = m
    return c


def _shift_dist(a, b) -> int:
    """a 를 고정하고 b 를 ±1px 옮겨 가며 가장 작은 픽셀 차이. 크기가 달라도 된다 (왼쪽 위 정렬 + 이동)."""
    H, W = max(a.shape[0], b.shape[0]) + 1, max(a.shape[1], b.shape[1]) + 1
    A = _pad(a, H, W)
    best = 1 << 30
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if 1 + dy < 0 or 1 + dx < 0:
                continue
            best = min(best, int(np.count_nonzero(A ^ _pad(b, H, W, dy, dx))))
    return best


# ---- 굵기 무관 비교 (골격 + 챔퍼 거리) ----
# UI 150% 글자는 밝은 바닥에서 가장자리까지 255 로 포화돼 획이 1~2px 굵어진다 (어두운 곳 1~2px → 밝은 돌바닥 2~3px).
# 기준값을 바꿔도 해결 안 됨 (실측: 255 만 써도 굵음). 그래서 픽셀 비교가 실패하면 획을 1px 골격으로 깎아
# 모양만 비교한다. 굵기가 달라도 골격은 같다.
SKEL_CANVAS = 28
SKEL_MAX = 1.2          # 골격 사이 평균 거리(양방향 합, px) 이하일 때만
SKEL_RATIO = 1.6        # 두 번째 후보(다른 글자)보다 이 배수 이상 가까울 때만
SKEL_SHIFTS = ((0, 0),)  # 가운데 정렬만 (챔퍼 거리는 1px 어긋남에 둔감. ±1 이동은 9배 느리고 결과 같음)


def _thin(m: np.ndarray) -> np.ndarray:
    """Zhang-Suen 세선화. bool → bool (1px 골격)."""
    img = np.pad(m.astype(np.uint8), 1)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            P = img
            p2, p3, p4, p5 = P[:-2, 1:-1], P[:-2, 2:], P[1:-1, 2:], P[2:, 2:]
            p6, p7, p8, p9 = P[2:, 1:-1], P[2:, :-2], P[1:-1, :-2], P[:-2, :-2]
            c = P[1:-1, 1:-1]
            nb = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            a = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            cond = ((p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)) if step == 0 else ((p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0))
            rm = (c == 1) & (nb >= 2) & (nb <= 6) & (a == 1) & cond
            if rm.any():
                img = img.copy(); img[1:-1, 1:-1][rm] = 0; changed = True
    return img[1:-1, 1:-1].astype(bool)


def _holes(mask: np.ndarray) -> tuple:
    """글자 안 구멍: (개수, 구멍 세로 중심들 / 높이). 0 은 세로로 긴 구멍 하나, 9 는 위쪽, 6 은 아래쪽, 8 은 둘.
    골격 비교에서 0↔9 처럼 모양이 비슷한 쌍을 가른다 (굵어져도 구멍 위치는 유지)."""
    import cv2
    bg = np.pad(~mask, 1, constant_values=True).astype(np.uint8)
    n, lab = cv2.connectedComponents(bg, connectivity=4)
    outside = lab[0, 0]
    h = mask.shape[0]
    cs = []
    for i in range(1, n):
        if i == outside:
            continue
        ys = np.nonzero(lab == i)[0]
        if len(ys) >= 1:
            cs.append(round(float((ys.mean() - 1) / max(h - 1, 1)), 2))
    return len(cs), tuple(sorted(cs))


def _holes_match(a: tuple, b: tuple) -> bool:
    return a[0] == b[0] and all(abs(x - y) <= 0.2 for x, y in zip(a[1], b[1]))


class _Skel:
    """가운데 정렬한 골격 좌표 + 거리 변환 (캔버스 SKEL_CANVAS²) + 구멍 모양."""
    __slots__ = ("pts", "dt", "shape", "holes")

    def __init__(self, mask):
        import cv2
        sk = _thin(mask)
        C = SKEL_CANVAS
        h, w = min(sk.shape[0], C - 4), min(sk.shape[1], C - 4)
        can = np.zeros((C, C), np.uint8)
        y0, x0 = (C - h) // 2, (C - w) // 2
        can[y0:y0 + h, x0:x0 + w] = sk[:h, :w]
        self.pts = np.argwhere(can > 0)
        self.dt = cv2.distanceTransform((1 - can).astype(np.uint8), cv2.DIST_L2, 3)
        self.shape = mask.shape
        self.holes = _holes(mask)

    def dist(self, other: "_Skel") -> float:
        """양방향 평균 거리, other 를 ±1px 옮겨 가며 최소."""
        if len(self.pts) == 0 or len(other.pts) == 0:
            return 1e9
        C = SKEL_CANVAS
        best = 1e9
        for dy, dx in SKEL_SHIFTS:
            if True:
                q = other.pts + (dy, dx)
                ok = (q[:, 0] >= 0) & (q[:, 0] < C) & (q[:, 1] >= 0) & (q[:, 1] < C)
                if not ok.all():
                    continue
                d1 = self.dt[q[:, 0], q[:, 1]].mean()
                p = self.pts - (dy, dx)
                ok2 = (p[:, 0] >= 0) & (p[:, 0] < C) & (p[:, 1] >= 0) & (p[:, 1] < C)
                if not ok2.all():
                    continue
                d2 = other.dt[p[:, 0], p[:, 1]].mean()
                best = min(best, float(d1 + d2))
        return best


def _trim(m):
    rows = np.where(m.any(axis=1))[0]
    cols = np.where(m.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return m[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


class GlyphLib:
    def __init__(self, fuzzy: bool = False):
        self.items: list[tuple[str, np.ndarray]] = []
        self.fuzzy = fuzzy
        self._cache: dict = {}          # fuzzy 결과 캐시 (같은 모양이 계속 나온다)
        self._skels = None              # [(label, _Skel)] 골격 템플릿 (처음 쓸 때 만든다)
        self.n_base = None              # 번들 템플릿 개수. 골격 비교는 번들(어두운 곳의 가는 글자)만 쓴다

    # ---- 저장/로드 ----
    def save(self, path):
        data = [{"label": l, "rows": ["".join("1" if v else "0" for v in r) for r in m]}
                for l, m in self.items]
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")

    @classmethod
    def load(cls, path, fuzzy: bool = False, extra=None):
        """extra = 사용 중 배운 글자 파일 (profiles/glyphs/<변형>.json). 번들 파일은 건드리지 않는다."""
        lib = cls(fuzzy=fuzzy)
        for p in (path, extra):
            if p is not None and Path(p).exists():
                for d in json.loads(Path(p).read_text(encoding="utf-8")):
                    lib.items.append((d["label"], np.array([[c == "1" for c in r] for r in d["rows"]])))
            if p is path:
                lib.n_base = len(lib.items)
        return lib

    def learn(self, label: str, mask: np.ndarray, path=None):
        """새 모양을 템플릿에 추가하고 (path 가 있으면) 그 파일에 덧붙여 저장."""
        if any(l == label and m.shape == mask.shape and (m == mask).all() for l, m in self.items):
            return False
        self.items.append((label, mask.copy())); self._cache.clear(); self._skels = None
        if path is not None:
            p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
            data.append({"label": label, "rows": ["".join("1" if v else "0" for v in r) for r in mask]})
            p.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        return True

    # ---- 학습/매칭 ----
    def add(self, label: str, mask: np.ndarray):
        if self.match(mask) != label:
            self.items.append((label, mask.copy()))

    def match(self, mask: np.ndarray) -> str | None:
        if self.fuzzy:
            return self.match_fuzzy(mask)[0]
        best, best_d = None, MAX_DIFF + 1
        for label, m in self.items:
            if m.shape != mask.shape:
                continue
            d = int(np.count_nonzero(m != mask))
            if d < best_d:
                best, best_d = label, d
        return best

    def match_fuzzy(self, mask: np.ndarray) -> tuple[str | None, int]:
        """(글자, 차이). 인정 못 하면 (None, 차이)."""
        key = (mask.shape, mask.tobytes())
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        per_label: dict[str, int] = {}
        h, w = mask.shape
        for label, m in self.items:
            if abs(m.shape[0] - h) > 2 or abs(m.shape[1] - w) > 2:
                continue                                  # 크기가 많이 다르면 볼 필요 없음
            d = _shift_dist(mask, m)
            if d < per_label.get(label, 1 << 30):
                per_label[label] = d
        out = (None, 1 << 30)
        if per_label:
            ranked = sorted(per_label.items(), key=lambda kv: kv[1])
            lab, d = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else 1 << 30
            n = np.count_nonzero(mask)
            limit = max(FUZZY_MAX, int(FUZZY_REL * n))
            near = d <= limit and second - d >= FUZZY_MARGIN
            far_ok = d <= FUZZY_FAR_REL * n and second >= FUZZY_FAR_RATIO * max(d, 1)
            if not near and far_ok:
                # 먼 일치는 골격으로 한 번 더 확인: 골격상 가장 가까운 글자도 같아야 인정
                # (밝은 바닥에서 배운 굵은 '0' 이 굵은 '9' 와 픽셀로는 가까울 수 있다)
                far_ok = self._skeleton_best(mask) == lab
            out = (lab if near or far_ok else None, d)
        if out[0] is None:
            sk = self.match_skeleton(mask)
            # 골격 결과가 픽셀상 가장 가까운 글자와도 같을 때만 (둘이 다르면 애매 → 모름)
            if sk[0] is not None and (not per_label or min(per_label, key=per_label.get) == sk[0]):
                out = sk
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[key] = out
        return out

    def _skeleton_best(self, mask: np.ndarray) -> str | None:
        """골격 거리로 가장 가까운 글자 (거리 조건 없이)."""
        self.match_skeleton(mask)
        g = _Skel(mask)
        h, w = mask.shape
        best, bd = None, 1e9
        for label, t in self._skels:
            if abs(t.shape[0] - h) > 3 or abs(t.shape[1] - w) > 4:
                continue
            d = g.dist(t)
            if d < bd:
                best, bd = label, d
        return best

    def skeleton_candidates(self, mask: np.ndarray, ratio: float = 1.3) -> set:
        """골격 비교로 '그럴 수 있는' 글자들 (가장 가까운 것의 ratio 배 이내). 0↔9 처럼 애매한 쌍을 둘 다 돌려준다."""
        self.match_skeleton(mask)                         # 템플릿 준비
        g = _Skel(mask)
        h, w = mask.shape
        per: dict[str, float] = {}
        for label, t in self._skels:
            if abs(t.shape[0] - h) > 3 or abs(t.shape[1] - w) > 4:
                continue
            d = g.dist(t)
            if d < per.get(label, 1e9):
                per[label] = d
        if not per:
            return set()
        best = min(per.values())
        if best > SKEL_MAX:
            return set()
        return {l for l, d in per.items() if d <= ratio * max(best, 0.1)}

    def match_skeleton(self, mask: np.ndarray) -> tuple[str | None, float]:
        """굵기 무관 비교 (픽셀 비교가 실패했을 때). (글자, 거리)."""
        if self._skels is None:
            seen, self._skels = set(), []
            # 배운 굵은 글자의 골격은 가지가 생겨 모양이 흐트러진다 (실측: 굵은 '0' 골격이 굵은 '9' 에 더 가까움)
            for label, m in self.items[:self.n_base]:
                k = (label, m.shape, m.tobytes())
                if k not in seen:
                    seen.add(k); self._skels.append((label, _Skel(m)))
        g = _Skel(mask)
        h, w = mask.shape
        per: dict[str, float] = {}
        for label, t in self._skels:
            if abs(t.shape[0] - h) > 3 or abs(t.shape[1] - w) > 4:
                continue
            d = g.dist(t)
            if d < per.get(label, 1e9):
                per[label] = d
        if not per:
            return None, 1e9
        ranked = sorted(per.items(), key=lambda kv: kv[1])
        lab, d = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 1e9
        ok = d <= SKEL_MAX and second >= SKEL_RATIO * max(d, 0.1)
        return (lab if ok else None), d

    def max_width(self) -> int:
        return max((m.shape[1] for _, m in self.items), default=0)

    def min_width(self) -> int:
        return min((m.shape[1] for _, m in self.items), default=1)

    def split_merged(self, g: Glyph, depth: int = 2) -> list[Glyph] | None:
        """붙어서 한 덩어리로 잘린 글자(안티앨리어싱 글꼴에서 가끔)를 쪼갠다. 모든 조각이 인정될 때만."""
        m = g.mask
        W = m.shape[1]
        lo = max(2, self.min_width() - 1)
        if depth <= 0 or W < 2 * lo:
            return None
        best = None
        for x in range(lo, W - lo + 1):
            left, right = _trim(m[:, :x]), _trim(m[:, x:])
            if left is None or right is None:
                continue
            ll, dl = self.match_fuzzy(left)
            if ll is None:
                continue
            gl = Glyph(g.x0, g.x0 + x, left, ll)
            lr, dr = self.match_fuzzy(right)
            if lr is not None:
                parts, cost = [gl, Glyph(g.x0 + x, g.x1, right, lr)], dl + dr
            else:
                sub = self.split_merged(Glyph(g.x0 + x, g.x1, right), depth - 1)
                if not sub:
                    continue
                parts, cost = [gl] + sub, dl + sum(self.match_fuzzy(p.mask)[1] for p in sub)
            if best is None or cost < best[0]:
                best = (cost, parts)
        return best[1] if best else None

    def learn_from_string(self, time_img, text: str):
        """'1분 55초' 처럼 공백 제외 글자 순서가 세그먼트 순서와 같다고 보고 라벨링."""
        chars = [c for c in text if c != " "]
        glyphs = segment(time_img)
        if len(chars) != len(glyphs):
            raise ValueError(f"글자 수 불일치: {text!r} → {len(chars)} vs 세그먼트 {len(glyphs)}")
        for c, g in zip(chars, glyphs):
            self.add(c, g.mask)


def read_time(time_img, lib: GlyphLib) -> TimeRead:
    glyphs = segment(time_img)
    if lib.fuzzy:                       # 안티앨리어싱 글꼴: 붙은 글자 쪼개기
        out = []
        for g in glyphs:
            if lib.match(g.mask) is None and g.mask.shape[1] > lib.max_width() + 1:
                parts = lib.split_merged(g)
                if parts:
                    out.extend(parts); continue
            out.append(g)
        glyphs = out
    text, unknown = "", []
    for g in glyphs:
        g.label = g.label or lib.match(g.mask)
        if g.label is None:
            unknown.append(g)
            text += "?"
        else:
            text += g.label
    # 시간은 반드시 '초' 또는 '분'으로 끝난다. 아니면 배경 잡음 → 모르는 글자로 취급하지 않음
    if not glyphs or glyphs[-1].label not in ("초", "분"):
        return TimeRead(None, text, [], plausible=False)
    if unknown:
        return TimeRead(None, text, unknown)

    # "N분 N초" / "N초" / "N분" 해석
    minutes = seconds = 0
    num = ""
    for c in text:
        if c.isdigit():
            num += c
        elif c == "분":
            minutes = int(num or 0); num = ""
        elif c == "초":
            seconds = int(num or 0); num = ""
        else:
            return TimeRead(None, text, [])
    if num:  # 단위 없이 끝난 숫자 → 해석 불가
        return TimeRead(None, text, [])
    return TimeRead(minutes * 60 + seconds, text, [])