"""
픽셀 자리 감시.

글자는 항상 최상단에 픽셀 그대로 그려진다는 전제. 캘리브레이션 때 각 행의 이름 획 픽셀 위치(마스크)를
저장해두고, 실행 중엔 그 자리의 색만 읽는다.
  정확히 255(불투명 흰) 비율 ≥ ON_RATIO → 활성
  회색 단색(209 또는 127) 비율 ≥ ON_RATIO → 비활성
  그 외                  → 모름 (이펙트가 글자를 덮었거나 목록이 바뀜)
런타임에 세그멘테이션/지문 비교가 없어서 배경과 완전히 무관하고, 애매하면 판단을 보류한다.
"""
from dataclasses import dataclass
import numpy as np

from core import screen
from core.strokes import stroke_masks

ON_RATIO = 0.85


@dataclass
class NameSite:
    """행 하나의 이름 획 자리."""
    x: int
    y: int
    mask: np.ndarray        # bool (h, w)

    def to_json(self):
        return {"x": int(self.x), "y": int(self.y), "shape": [int(v) for v in self.mask.shape],
                "bits": np.packbits(self.mask.ravel()).tobytes().hex()}

    @classmethod
    def from_json(cls, d):
        h, w = d["shape"]
        bits = np.unpackbits(np.frombuffer(bytes.fromhex(d["bits"]), np.uint8))[:h * w]
        return cls(d["x"], d["y"], bits.reshape(h, w).astype(bool))


@dataclass
class Reading:
    state: str        # "on" | "off" | "unknown"
    white: float      # 획 자리 중 흰색 비율
    gray: float
    n: int


def make_site(frame, text_rect, name_range) -> NameSite:
    """캘리브레이션: 텍스트 rect 안 name_range(x0, x1) 의 획 마스크를 저장."""
    x, y, w, h = text_rect
    a, b = name_range
    sub = frame[y:y + h, x + a:x + b + 1]
    white, gray, _ = stroke_masks(sub)
    if screen.current().fuzzy:
        cut = _suffix_start(sub, white | gray)
        if cut is not None:                   # 연장 접미어가 붙은 채로 캘리브레이션 → 기본 이름까지만 자리로
            sub, white, gray = sub[:, :cut], white[:, :cut], gray[:, :cut]
    if screen.current().fuzzy and gray.any():
        # 안티앨리어싱 글꼴: 회색 글자 가장자리는 배경과 섞인 중간 밝기라, 글자가 흰색으로 바뀌어도 250 이 안 된다
        # → 활성 판정이 84% 에서 멈춰 '모름'. 완전히 덮인 픽셀(회색 최댓값 근처)만 자리로 쓴다.
        #   실측: 185px → 38px, 회색 100%/흰색 100% 로 깔끔하게 갈림
        mn = sub.min(axis=2).astype(np.int16)
        gray = gray & (mn >= int(mn[gray].max()) - 10)
    return NameSite(int(x + a), int(y), white | gray)


def _suffix_start(sub, strokes):
    """'비바체(투안의 노래)' 처럼 분홍 접미어가 붙어 있으면 기본 이름이 끝나는 열(+1), 없으면 None.
    접미어는 흰 '(' + 분홍 글자 + 흰 ')' → 첫 분홍 열 바로 앞의 좁은 흰 덩어리 '(' 까지 뺀다.
    (전엔 접미어까지 자리로 저장돼, 접미어가 사라지면 그 자리가 배경이라 '판정 불가', 연장도 영영 못 봄)"""
    from core.strokes import pink_mask
    pk = np.nonzero(pink_mask(sub).any(axis=0))[0]
    if len(pk) == 0:
        return None
    p0 = int(pk[0])
    cols = np.nonzero(strokes[:, :p0].any(axis=0))[0]
    if len(cols) == 0:
        return None
    runs, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > 1:
            runs.append((start, prev)); start = c
        prev = c
    runs.append((start, prev))
    # '(' 는 대부분 분홍으로 섞여 그려진다 (실측). 흰 조각이 분홍에 딱 붙어(≤1px) 좁게 남아 있으면 그것도 '(' 로 보고 뺀다
    last = runs[-1]
    if len(runs) >= 2 and p0 - last[1] <= 2 and last[1] - last[0] + 1 <= screen.px(4):
        return int(runs[-2][1]) + 1
    return int(last[1]) + 1


def read_site(frame, site: NameSite) -> Reading:
    """획 자리 픽셀 색으로 판정. 활성 = 정확히 255. 비활성 = 회색 단색 (209, 던전 등 일부 상태에선 127).
    배경과 무관하게 이 두 값만 나온다 (실측: 어두운 맵·안개·돌·마을 전부 209)."""
    h, w = site.mask.shape
    sub = frame[site.y:site.y + h, site.x:site.x + w]
    if sub.shape[:2] != (h, w):
        return Reading("unknown", 0.0, 0.0, 0)
    px = sub[site.mask].astype(np.int16)
    n = len(px)
    if n == 0:
        return Reading("unknown", 0.0, 0.0, 0)
    mx, mn = px.max(axis=1), px.min(axis=1)
    neutral = (mx - mn) <= 12
    white = float((mn >= 250).mean())
    gray = float((neutral & (mn >= 100) & (mn <= 220)).mean())
    state = "on" if white >= ON_RATIO else "off" if gray >= ON_RATIO else "unknown"
    return Reading(state, white, gray, n)