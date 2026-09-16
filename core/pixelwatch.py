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
    return NameSite(int(x + a), int(y), white | gray)


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