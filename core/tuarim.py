"""
투아림 읽기 + 알림 규칙 (Qt·Windows 없음 → 테스트 가능).

화면: 보라 원 안의 도르카 숫자(0~15) + 분홍 칸 + 그 아래 부스트 %(0~100).
  - 분홍 칸 = 기준점 (UI 100% 23×9, 150% 34×14). 숫자 자리는 칸 왼쪽 위 기준 고정 위치
  - 글자 = 순백(무채색 ≥250). 실측 (샘플 219장, 4K·QHD·150% 두 글꼴): 틀리게 읽은 것 0
  - UI 100% 는 해상도와 무관하게 픽셀까지 같다 (4K = QHD). 150% 는 글꼴별로, 같은 글자도 위치에 따라 조금씩 다름 → 여러 모양
  - 글자 세트: assets/tuarim/<UI 변형>.json (core/screen.py 의 키)

부스트: 전투 시간 600초 누적이면 100% → 1% = 6초. 남은 시간 = (100 − %) × 6초 (전투가 이어진다면).
"""
from dataclasses import dataclass, field
import json
from pathlib import Path

import numpy as np

from core.digits import GlyphLib, Glyph, _trim

PINK = (23, 9)                 # 분홍 칸 크기 (UI 100%)
ZONE_DORCA = (-38, -14, 26, 18)   # 칸 왼쪽 위 기준 (dx, dy, w, h), UI 100% 픽셀 (150% 는 ×1.5)
ZONE_PCT = (-12, 12, 38, 14)    # "100%" 는 나눔고딕 150% 에서 칸 왼쪽 밖까지 나간다 (전엔 '1' 이 잘려 0% 로 읽혔음)
SECS_PER_PCT = 6.0             # 600초 / 100%


@dataclass
class TuarimRead:
    found: bool                # 분홍 칸을 찾았나 (영역이 맞나)
    dorca: int | None = None   # 0~15, 못 읽으면 None
    pct: int | None = None     # 0~100


def _white(zone):
    px = zone.astype(np.int16)
    mn, mx = px.min(axis=2), px.max(axis=2)
    return (mn >= 250) & ((mx - mn) <= 12)


def find_pink(crop, scale=1.0):
    """분홍 칸 (x, y, w, h). 크기가 맞는 것만 (뒤에 분홍 이펙트가 깔리면 커져서 제외)."""
    import cv2
    b, g, r = (crop[..., i].astype(np.int16) for i in range(3))
    m = ((r > 220) & (b > 220) & (g < r - 15) & (g > 120)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    want_w, want_h = round(PINK[0] * scale), round(PINK[1] * scale)
    best = None
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if abs(w - want_w) <= 2 and abs(h - want_h) <= 2 and (best is None or a > best[4]):
            best = (x, y, w, h, a)
    return best[:4] if best else None


def _zone(crop, pink, z, scale):
    """숫자 자리 잘라내기 → (영상, 왼쪽에서 드래그 영역 밖이라 검게 채운 열 수)."""
    x, y = pink[0], pink[1]
    y0, x0 = y + round(z[1] * scale), x + round(z[0] * scale)
    y1, x1 = y + round((z[1] + z[3]) * scale), x + round((z[0] + z[2]) * scale)
    if y1 <= 0 or x1 <= 0 or y0 >= crop.shape[0] or x0 >= crop.shape[1]:
        return None, 0              # 영역이 숫자 자리를 아예 안 덮음
    # 드래그 영역 밖은 검게 채워 같은 크기로 (글자 줄 위치가 그대로여야 band 가 맞는다)
    out = np.zeros((y1 - y0, x1 - x0, 3), crop.dtype)
    sy0, sx0 = max(0, y0), max(0, x0)
    sy1, sx1 = min(crop.shape[0], y1), min(crop.shape[1], x1)
    out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = crop[sy0:sy1, sx0:sx1]
    return out, sx0 - x0


def _segments(m, band, min_h):
    """글자 줄(band) 안의 열 묶음 → 글자 조각. 줄 밖(테두리 얼룩·바닥)은 버린다."""
    y0, y1 = band
    m = m.copy()
    m[:max(0, y0 - 1)] = False
    m[y1 + 2:] = False
    cols = m.any(axis=0)
    out, x = [], 0
    while x < len(cols):
        if not cols[x]:
            x += 1; continue
        a = x
        while x < len(cols) and cols[x]:
            x += 1
        g = _trim(m[:, a:x])
        if g is not None and g.shape[0] >= min_h:
            out.append(Glyph(a, x, g))
    return out


class _ZoneReader:
    def __init__(self, d):
        self.band, self.min_h = tuple(d["band"]), int(d["min_h"])
        self.lib = GlyphLib(fuzzy=True)          # ±1px·몇 픽셀 차이 허용 (밝은 바닥이 글자에 붙는 경우), 애매하면 모름
        for g in d["glyphs"]:
            self.lib.items.append((g["label"], np.array([[c == "1" for c in r] for r in g["rows"]])))
        self.lib.n_base = len(self.lib.items)

    def read(self, zone, left_clip=0) -> str | None:
        text = ""
        segs = _segments(_white(zone), self.band, self.min_h)
        if segs and left_clip and segs[0].x0 <= left_clip + 1:
            return None             # 글자가 드래그 영역 왼쪽 끝에 닿음 → 앞자리가 잘렸을 수 있다 ("100%" → "00%") → 모름
        for g in segs:
            label, _ = self.lib.match_fuzzy(g.mask)
            if label is not None:
                text += label; continue
            parts = self.lib.split_merged(g)       # 붙어서 한 덩어리 ("1%")
            if not parts:
                return None
            text += "".join(p.label for p in parts)
        return text


class TuarimReader:
    def __init__(self, glyph_file: Path, scale: float):
        d = json.loads(Path(glyph_file).read_text(encoding="utf-8"))
        self.scale = scale
        self.dorca = _ZoneReader(d["dorca"])
        self.pct = _ZoneReader(d["pct"])

    def read(self, crop) -> TuarimRead:
        pink = find_pink(crop, self.scale)
        if pink is None:
            return TuarimRead(False)
        r = TuarimRead(True)
        (zd, cd), (zp, cp) = _zone(crop, pink, ZONE_DORCA, self.scale), _zone(crop, pink, ZONE_PCT, self.scale)
        if zd is not None:
            t = self.dorca.read(zd, cd)
            if t and t.isdigit() and int(t) <= 15 and (t == "0" or not t.startswith("0")):
                r.dorca = int(t)
        if zp is not None:
            t = self.pct.read(zp, cp)
            n = t[:-1] if t and t.endswith("%") else ""
            # 앞자리 0 은 실제로 안 나온다 ("0%" 만). "00%" = '100%' 의 '1' 이 잘린 것 → 모름
            if n.isdigit() and int(n) <= 100 and (n == "0" or not n.startswith("0")):
                r.pct = int(n)
        return r


# ---------------------------------------------------------------- 알림 규칙
@dataclass
class TuarimEvent:
    kind: str                  # "soon" | "burst" | "dorca_low"
    value: int | None = None   # soon: 남은 초 / dorca_low: 도르카 값


@dataclass
class TuarimTracker:
    """값 안정화(STABLE 프레임 연속) + 한 번씩만 알리기.
      - 곧 투아림: 부스트가 soon_pct 이상이 되는 순간 1회 (남은 초 = (100−%)×6). 투아림이 터져 %가 떨어지면 다시 준비
      - 투아림!: 부스트가 100% 가 되는 순간 (게임에서 100% 즉시 발동). 예전엔 '높았다가 낮아질 때' 였는데
        그건 투아림이 끝나고 게이지가 빠진 뒤라 50초쯤 늦었다. 다시 준비 = 부스트가 90% 아래로 내려갔을 때
      - 도르카 부족: dorca_low 이하로 떨어질 때 1회, 그 위로 올라오면 다시 준비. 0 이면 안 씀"""
    soon_pct: int = 95
    dorca_low: int = 0
    STABLE: int = 2
    dorca: int | None = None
    pct: int | None = None
    _cand: dict = field(default_factory=dict)      # 이름 → (값, 연속 횟수)
    _soon_done: bool = False
    _low_done: bool = False
    _burst_done: bool = False

    def _stable(self, name, v):
        if v is None:
            return None
        pv, n = self._cand.get(name, (None, 0))
        n = n + 1 if pv == v else 1
        self._cand[name] = (v, n)
        return v if n >= self.STABLE else None

    def update(self, r: TuarimRead) -> list[TuarimEvent]:
        ev = []
        if not r.found:
            return ev
        p = self._stable("pct", r.pct)
        if p is not None and p != self.pct:
            prev, self.pct = self.pct, p
            if p >= 100:
                if prev is not None and not self._burst_done:
                    ev.append(TuarimEvent("burst"))      # 100% = 발동 (켤 때 이미 100% 면 말하지 않음)
                self._burst_done = True
            elif p < 90:
                self._burst_done = False                 # 게이지가 빠졌으면 다음 바퀴 준비
            if p < self.soon_pct - 5:
                self._soon_done = False                  # 많이 내려갔으면 (투아림을 못 보고 지나간 경우 등) 다시 준비
            if self.soon_pct and p >= self.soon_pct and not self._soon_done and p < 100:
                self._soon_done = True
                ev.append(TuarimEvent("soon", int(round((100 - p) * SECS_PER_PCT))))
        d = self._stable("dorca", r.dorca)
        if d is not None and d != self.dorca:
            first, self.dorca = self.dorca is None, d
            if first:
                self._low_done = self.dorca_low and d <= self.dorca_low   # 시작할 때 이미 낮은 건 말하지 않음 (오르면 다시 준비)
            elif self.dorca_low:
                if d <= self.dorca_low and not self._low_done:
                    self._low_done = True
                    ev.append(TuarimEvent("dorca_low", d))
                elif d > self.dorca_low:
                    self._low_done = False
        return ev

    def eta(self) -> int | None:
        """지금 % 기준 남은 초 (표시용)."""
        return None if self.pct is None else int(round((100 - self.pct) * SECS_PER_PCT))


def _time(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}분" + (f" {s}초" if s else "") if m else f"{s}초"


def event_text(e: TuarimEvent) -> str:
    if e.kind == "soon":
        return f"곧 투아림 (약 {_time(e.value)})"
    if e.kind == "burst":
        return "투아림!"
    if e.kind == "dorca_low":
        return f"도르카 부족 ({e.value})"
    return e.kind


def speech_text(e: TuarimEvent) -> str:
    """음성 문구 (짧게)."""
    if e.kind == "soon":
        return f"투아림 {_time(e.value)} 전"
    if e.kind == "burst":
        return "투아림"
    return "도르카 부족"
