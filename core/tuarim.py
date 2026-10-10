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


def find_box(crop, scale=1.0):
    """분홍 칸을 색이 아니라 모양으로: 칸 맨 윗줄 = 흰 가로줄 (폭 23), 바로 아래 줄은 분홍.
    HDR 이 꺼진 보통 화면에선 칸이 진한 분홍→회색 그라데이션이라 색 기준(find_pink)으로는 못 찾는다.
    반환값은 find_pink 와 같은 기준 (흰 줄 바로 아래부터 23×9)."""
    want = round(PINK[0] * scale)
    px = crop.astype(np.int16)
    b, g, r = px[..., 0], px[..., 1], px[..., 2]
    mn, mx = px.min(axis=2), px.max(axis=2)
    white = (mn >= 180) & ((mx - mn) <= 40) & (r >= 200)     # 흰색~분홍빛 흰색 (150% 는 윗줄이 분홍과 섞여 (220,191,210))
    pink = (r >= 140) & (r - g >= 40) & (b - g >= 20)
    best = None
    for y in range(crop.shape[0] - 2):
        row = white[y]
        x = 0
        while x < len(row):
            if not row[x]:
                x += 1; continue
            a = x
            while x < len(row) and row[x]:
                x += 1
            w = x - a
            if abs(w - want) <= 2 and pink[y + 1, a:x].mean() >= 0.8 and pink[y + 2, a:x].mean() >= 0.8:
                if best is None or abs(w - want) < abs(best[2] - want):
                    best = (a, y + 1, w, round(PINK[1] * scale))
    return best


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


class _GrayZoneReader:
    """HDR 이 꺼진 보통 화면: 글자가 가늘고 가장자리가 흐려 순백(≥250)으로는 안 잡힌다 → 밝기 그대로 비교.
    (HDR 화면은 밝게 변환돼 획이 255 로 꽉 차서 굵은 흑백 모양으로 읽혔다)"""

    def __init__(self, d):
        from core.digits import GrayLib
        self.band = tuple(d["band"])
        self.right = bool(d.get("right", False))      # 오른쪽부터 읽기 (가는 글꼴 %)
        self.mask_min, self.neutral = d.get("mask_min", 170), d.get("neutral", 40)
        self.lib = GrayLib()
        for g in d["glyphs"]:
            self.lib.items.append((g["label"], np.array(g["v"], np.float32) / 255.0))

    @staticmethod
    def mask(zone):
        px = zone.astype(np.int16)
        mn, mx = px.min(axis=2), px.max(axis=2)
        return (mn >= 170) & ((mx - mn) <= 40)

    def read(self, zone, left_clip=0) -> str | None:
        if self.right:
            return self._read_right(zone)
        m = self.mask(zone); y0, y1 = self.band
        m[:y0] = False; m[y1 + 1:] = False
        g = zone.min(axis=2).astype(np.float32) / 255.0
        cols = m.any(axis=0)
        text, x = "", 0
        while x < len(cols):
            if not cols[x]:
                x += 1; continue
            a = x
            while x < len(cols) and cols[x]:
                x += 1
            if m[:, a:x].sum() < 3:
                continue
            if left_clip and a <= left_clip + 1 and not text:
                return None                     # 앞자리가 영역 밖으로 잘렸을 수 있다
            label = self.lib.match_patch(g[y0:y1 + 1, max(0, a - 1):x + 1])
            if label is None:
                return None
            text += label
        return text


    def _segments(self, zone):
        px = zone.astype(np.int16)
        mn, mx = px.min(axis=2), px.max(axis=2)
        m = (mn >= self.mask_min) & ((mx - mn) <= self.neutral)
        y0, y1 = self.band
        m[:y0] = False; m[y1 + 1:] = False
        cols = m.any(axis=0)
        out, x = [], 0
        while x < len(cols):
            if not cols[x]:
                x += 1; continue
            a = x
            while x < len(cols) and cols[x]:
                x += 1
            if m[:, a:x].sum() >= 3:
                out.append((a, x))
        return out

    def _read_right(self, zone) -> str | None:
        """가는 글꼴(UI 배율 조정 100%, HDR 끔): 오른쪽 정렬된 '…%' 를 오른쪽부터 읽는다.
        첫 덩어리는 '%', 그다음 숫자. 숫자가 아닌 덩어리가 3px 넘게 떨어져 있으면 거기서 끝 (밝은 바닥 얼룩)."""
        g = zone.min(axis=2).astype(np.float32) / 255.0
        y0, y1 = self.band
        text, prev_a = "", None
        for a, b in reversed(self._segments(zone)):
            label = self.lib.match_patch(g[y0:y1 + 1, max(0, a - 1):b + 1])
            if not text:
                if label != "%":
                    return None
            elif label is None or label == "%":
                if prev_a - b >= 3 and len(text) >= 2:
                    break
                return None
            text = label + text
            prev_a = a
        return text if len(text) >= 2 else None


def _valid_dorca(t):
    return bool(t) and t.isdigit() and int(t) <= 15 and (t == "0" or not t.startswith("0"))


def _valid_pct(t):
    n = t[:-1] if t and t.endswith("%") else ""
    # 앞자리 0 은 실제로 안 나온다 ("0%" 만). "00%" = '100%' 의 '1' 이 잘린 것 → 모름
    return int(n) if n.isdigit() and int(n) <= 100 and (n == "0" or not n.startswith("0")) else None


class TuarimReader:
    """glyph_file: HDR 화면(밝게 변환됨) 글자 세트. 같은 폴더의 sdr_<변형>.json 이 있으면 보통 화면(HDR 끔)도 읽는다.
    칸 찾기: 색(밝은 분홍)으로 못 찾으면 모양(흰 윗줄 + 분홍)으로 — HDR 이 꺼지면 칸이 진한 분홍→회색이라."""

    def __init__(self, glyph_file: Path, scale: float):
        glyph_file = Path(glyph_file)
        d = json.loads(glyph_file.read_text(encoding="utf-8"))
        self.scale = scale
        self.dorca = _ZoneReader(d["dorca"])
        self.pct = _ZoneReader(d["pct"])
        self.sdr = None
        sf = glyph_file.parent / f"sdr_{glyph_file.stem}.json"
        if sf.exists():
            sd = json.loads(sf.read_text(encoding="utf-8"))
            self.sdr = (_GrayZoneReader(sd["dorca"]), _GrayZoneReader(sd["pct"]))

    def _read_with(self, readers, crop, box) -> TuarimRead:
        r = TuarimRead(True)
        (zd, cd), (zp, cp) = _zone(crop, box, ZONE_DORCA, self.scale), _zone(crop, box, ZONE_PCT, self.scale)
        if zd is not None:
            t = readers[0].read(zd, cd)
            if _valid_dorca(t):
                r.dorca = int(t)
        if zp is not None:
            r.pct = _valid_pct(readers[1].read(zp, cp))
        return r

    def read(self, crop) -> TuarimRead:
        pink = find_pink(crop, self.scale)
        if pink is not None:
            r = self._read_with((self.dorca, self.pct), crop, pink)
            if r.dorca is not None or r.pct is not None or self.sdr is None:
                return r
        # 보통 화면(HDR 끔) 세트는 모양으로 찾은 칸 기준으로 만들었다 (150% 에선 색 기준과 1~2px 다름)
        box = find_box(crop, self.scale)
        if box is None:
            return TuarimRead(pink is not None)
        if self.sdr is None:
            return TuarimRead(True)
        return self._read_with(self.sdr, crop, box)


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
