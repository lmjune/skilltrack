"""
생명력 / 마나 / 스태미나 막대 → 비율 (숫자를 읽지 않고 색으로). Qt·Windows 없음 → 테스트 가능.

막대 행마다 픽셀을 '찬 색 / 빈 색' 으로 가르고 (색 비율로 — 아래 설명), 열마다 다수결 →
왼쪽 찬·오른쪽 빈 계단에 가장 잘 맞는 경계 = 비율. 숫자·글꼴·해상도·UI 크기와 무관 (막대 길이만 달라짐).
실측 오차 1% 이내: 4K UI 100% 45장, 4K UI 150% 마비옛체 38장 (150% 는 테두리가 섞여 그려져도 됨). 경계가 숫자 밑에 있어도 (글자 외곽선 = 막대 색을 어둡게 한 것) 1% 남짓.
"""
from dataclasses import dataclass, field
import time

import cv2
import numpy as np

# 찬 곳·빈 곳은 '색 비율'(채널끼리의 비)로 가른다. 밝기와 무관 →
#   - 두 그림 방식(어두운 단색 / 밝은 그라데이션) 모두 같은 기준
#   - 숫자 글자의 어두운 외곽선 = 그 밑 막대 색을 어둡게 한 것 → 비율이 그대로라 글자 밑 경계도 읽힌다
#   - 화면 전환으로 어두워져도 비율은 그대로 (거짓 '부족' 안 남). 하얗게 바래면 채도가 떨어져 '모름'
# 실측 (RGB): 생명력 찬 (255,109,237)(228,76,163)(207,64,145)(139,43,98) 빈 (196,65,103)(135,46,71)(119,36,60)(80,24,40)
#             마나   찬 (152,179,255)(105,122,201)(91,108,182)(61,72,122)  빈 (67,49,132)(48,35,90)(25,17,52)
#             스태미나 찬 (255,206,41)(233,185,32)(157,125,21)         빈 (188,174,41)(170,157,32)(114,105,21)
#             스태미나 밝은 방식 안쪽은 찬 곳·빈 곳 모두 (255,255,59) (밝기가 넘쳐 잘림) → 비율 ≥0.97 은 '모름'
# 하얗게 바래는 전환: 가장 어두운 채널이 올라간다 (최소/최대 비율) → 막대 원래 범위를 넘으면 '모름'
NAMES = {"hp": "생명력", "mp": "마나", "sp": "스태미나"}
HUE = {"hp": (148, 179), "mp": (100, 132), "sp": (15, 36)}   # 막대 색 계열 (OpenCV H)
# 비율 = 채널 a / 채널 b, 찬 곳이 기준보다 큰지(>)·작은지(<), 이 이상이면 모름
RATIO = {"hp": (2, 0, 0.62, ">", 9.0),    # B/R  찬 0.70~0.93, 빈 0.50~0.53
         "mp": (1, 2, 0.49, ">", 9.0),    # G/B  찬 0.59~0.70, 빈 0.33~0.39
         "sp": (1, 0, 0.865, "<", 0.97)}  # G/R  찬 0.79~0.81, 빈 0.92~0.93
WASH = {"hp": 0.5, "mp": 0.66, "sp": 0.3}   # 최소 채널/최대 채널 상한 (실측 hp ≤0.43, mp ≤0.60, sp ≤0.23)
SP_RED = 0.92       # 스태미나 밝은 방식: 빨강이 안쪽 빨강의 이만큼 이상이면 찬 곳 (찬 1.0, 빈 0.74~0.84)
MIN_V = 35          # 이보다 어두운 픽셀은 안 씀
MIN_COLS = 20       # 판정된 열이 이만큼은 있어야 그 막대로 인정
MIN_KNOWN = 0.6     # 막대 폭 중 판정된 열 비율


def _split(c):
    """열 판정(1 찬 / -1 빈 / 0 모름) → 찬 곳 끝 위치 b (0..n). 왼쪽 찬·오른쪽 빈 계단에 가장 잘 맞는 자리.
    모르는 열은 건너뛰고, 같은 점수가 여럿이면 그 가운데."""
    left_empty = np.concatenate([[0], np.cumsum(c == -1)])                 # [0,b) 의 빈 열 수
    right_fill = np.concatenate([np.cumsum((c == 1)[::-1])[::-1], [0]])   # [b,n) 의 찬 열 수
    err = left_empty + right_fill
    best = np.nonzero(err == err.min())[0]
    return (int(best[0]) + int(best[-1])) / 2


def read_bars(crop_bgr) -> dict:
    """{"hp": 0.0~1.0 | None, ...}. None = 그 막대를 못 찾음 (영역 밖·화면 전환 중 등)."""
    rgb = crop_bgr[..., ::-1].astype(np.float32)
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    Hh, S, V = hsv[..., 0].astype(np.int16), hsv[..., 1], hsv[..., 2]
    out = {}
    for key, (h0, h1) in HUE.items():
        out[key] = None
        fam = (S >= 90) & (V >= MIN_V) & (Hh >= h0) & (Hh <= h1)
        rows = np.nonzero(fam.sum(axis=1) >= max(8, crop_bgr.shape[1] // 6))[0]
        if len(rows) < 3:
            continue
        # 가장 긴 연속 행 묶음 = 그 막대
        runs, a = [], rows[0]
        for i in range(1, len(rows) + 1):
            if i == len(rows) or rows[i] != rows[i - 1] + 1:
                runs.append((a, rows[i - 1])); a = rows[i] if i < len(rows) else a
        y0, y1 = max(runs, key=lambda r: r[1] - r[0])
        ca, cb, thr, sign, skip = RATIO[key]
        band, m = rgb[y0:y1 + 1], fam[y0:y1 + 1]
        r = band[..., ca] / np.maximum(band[..., cb], 1.0)
        m = m & (r < skip) & (band.min(axis=2) <= WASH[key] * band.max(axis=2))
        is_fill = (r > thr) if sign == ">" else (r < thr)
        if key == "sp":
            # 밝은 방식: 안쪽 (255,255,59) 는 찬·빈 같음. UI 150% 에선 1px 테두리가 안쪽 색과 섞여 비율로는 못 가른다
            # (찬 (255,233,46) / 빈 (214,198,46) — G/R 둘 다 0.92). 대신 빨강 밝기: 찬 곳은 안쪽만큼(255), 빈 곳은 어둡다
            # (100% 188, 150% 214). 안쪽 빨강을 기준으로 삼으니 화면이 어두워져도 같은 비율.
            raw = rgb[y0:y1 + 1]
            clip = fam[y0:y1 + 1] & (r >= skip)
            if clip.sum() >= 20:
                ref = float(np.median(raw[..., 0][clip]))
                is_fill = is_fill | (raw[..., 0] >= SP_RED * ref)
        f = (m & is_fill).sum(axis=0)
        e = (m & ~is_fill).sum(axis=0)
        c = np.where(f > e, 1, np.where(e > f, -1, 0))
        xs = np.nonzero(c)[0]
        if len(xs) < MIN_COLS:
            continue
        x0, x1 = int(xs[0]), int(xs[-1])
        c = c[x0:x1 + 1]
        if np.count_nonzero(c) < MIN_KNOWN * len(c):
            continue
        out[key] = max(0.0, min(1.0, _split(c) / len(c)))
    return out


# ---------------------------------------------------------------- 알림 규칙
@dataclass
class BarCfg:
    enabled: bool = False
    pct: int = 30              # 이 % 이하면 '부족'
    text: bool = True          # 자원 알림 칸에 글씨
    edge: bool = True          # 화면 가장자리 효과
    sound: str = "none"        # voice | effect | none
    shield_only: bool = False  # (마나) 마나실드가 켜져 있을 때만 화면 효과
    msg: str = ""              # 알림 문구 (비우면 "생명력 부족"). 글씨 칸엔 "문구 22%", 음성은 문구 그대로


DEFAULTS = {
    "hp": BarCfg(enabled=True, pct=30, text=True, edge=True),
    "mp": BarCfg(enabled=True, pct=25, text=True, edge=True, shield_only=True),
    "sp": BarCfg(enabled=False, pct=20, text=True, edge=False),
}
RELEASE = 5         # 기준보다 이만큼(%) 위로 회복해야 '부족' 해제 (기준 근처에서 출렁일 때 계속 울리지 않게)
SMOOTH = 3          # 최근 몇 번 읽은 값의 중앙값 (숫자가 바뀌는 순간 한 프레임 튐 거르기)
HOLD = 1.0          # 이 시간(초) 동안 계속 기준 이하로 읽혀야 '부족' (화면 전환 순간의 잘못 읽은 값 거르기)


@dataclass
class BarState:
    low: bool = False
    pct: int | None = None              # 지금 % (중앙값)
    since: float | None = None          # 기준 이하로 읽히기 시작한 시각 (아직 '부족' 전)
    recent: list = field(default_factory=list)


@dataclass
class BarEvent:
    key: str            # hp | mp | sp
    pct: int


class BarTracker:
    """막대 비율 → 부족 상태 (들어갈 때 이벤트 1회) + 화면 효과 세기."""

    def __init__(self, cfgs: dict):
        self.cfgs = cfgs
        self.st = {k: BarState() for k in HUE}

    def update(self, ratios: dict, now: float | None = None) -> list[BarEvent]:
        """now: 시각(초). 기준 이하가 HOLD 초 이어져야 '부족'. 못 읽은 프레임(화면 전환·막대 안 보임)은 처음부터 다시 잰다."""
        now = time.monotonic() if now is None else now
        ev = []
        for k, r in ratios.items():
            s, c = self.st[k], self.cfgs.get(k)
            if r is None:
                s.recent, s.since = [], None
                continue
            s.recent = (s.recent + [round(r * 100)])[-SMOOTH:]
            s.pct = int(np.median(s.recent))
            if not (c and c.enabled):
                s.low, s.since = False, None
                continue
            if not s.low:
                if s.pct <= c.pct and len(s.recent) >= SMOOTH:
                    if s.since is None:
                        s.since = now
                    if now - s.since >= HOLD:
                        s.low, s.since = True, None
                        ev.append(BarEvent(k, s.pct))
                else:
                    s.since = None
            elif s.pct >= c.pct + RELEASE:
                s.low = False
        return ev

    def edge_levels(self, shield_on=None) -> dict:
        """화면 효과: {key: 1(부족) | 2(기준의 절반 이하, 위험)}. shield_on: 마나실드 켜짐 (None = 모름 → 설정 무시)."""
        out = {}
        for k, s in self.st.items():
            c = self.cfgs.get(k)
            if not (c and c.enabled and c.edge and s.low):
                continue
            if c.shield_only and shield_on is False:
                continue
            out[k] = 2 if s.pct is not None and s.pct <= c.pct / 2 else 1
        return out

    def text_rows(self) -> list[tuple[str, int]]:
        """자원 알림 칸에 띄울 것: [(key, %)]."""
        return [(k, s.pct) for k, s in self.st.items()
                if s.low and self.cfgs.get(k) and self.cfgs[k].text and s.pct is not None]


def default_msg(key) -> str:
    return f"{NAMES[key]} 부족"


def label(key, cfg=None) -> str:
    """글씨 칸·로그에 쓰는 이름: 직접 쓴 문구 또는 '생명력'."""
    return (cfg.msg.strip() if cfg and cfg.msg.strip() else NAMES[key])


def event_text(e: BarEvent, cfg=None) -> str:
    return f"{label(e.key, cfg)} {e.pct}%"


def speech_text(e: BarEvent, cfg=None) -> str:
    return cfg.msg.strip() if cfg and cfg.msg.strip() else default_msg(e.key)
