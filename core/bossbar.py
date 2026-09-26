"""
보스 체력바 + 디버프 띠 읽기. 캡처한 프레임(BGR)만 보고 판단한다.

실측 구조 (4K, UI 100%, 픽셀 단위로 고정):
  - 체력바 이름 글자 = 순백(255) 17행. 바 색은 가변(보라/녹/빨강…)이라 색은 쓰지 않는다.
  - 오른쪽 끝 "%" 글자 마스크가 항상 같다 → 이것으로 바 유무·위치(anchor)를 잡는다.
    "%" 오른쪽 끝 x 에서 이름 왼쪽 x 까지 496px, 바 폭은 고정.
  - 디버프 띠: 이름 글자 첫 행보다 45행 위, 14×14 아이콘 프레임(1px 어두운 테두리, 내부 12×12), 피치 18.
    아이콘은 왼쪽부터 빈칸 없이 채워진다. 띠의 x 시작은 바에 대해 고정이 아니어서(실측 16px 차이) 테두리를 스캔해 찾는다.
  - 아이콘 아래 라벨: 이름 글자보다 26행 위, 7행 높이. 상태창과 같은 5×7 숫자 폰트 + 'M'(7×7).
    "4M"=4분, "40"=40초. 라벨이 없는 아이콘(시간 없는 디버프)도 있다.
  - 띠가 없는 보스(구형 레이드)는 바만 있고 아이콘 프레임이 하나도 안 잡힌다 → 자동으로 감시 안 함.

주의: 이 모듈의 규칙은 원본 픽셀(dxcam/무손실 PNG)에서만 성립한다. 뷰어로 다시 저장한 이미지는 글자가 255가 아니다.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path

import cv2
import numpy as np

from core import screen
from core.digits import GlyphLib, segment

# ---- 고정 치수 ----
PCT_ROWS = ['000100000001000', '010010000010000', '010001000010000', '100001000100000', '010001000100000',
            '010010001000000', '000100001000000', '000000010000100', '000000100010001', '000000100010001',
            '000001000010001', '000001000010001', '000010000010001', '000000000000100']
# 실제 화면(dxcam)에선 바 글자가 굵게(2px 획) 그려진다. 게임 스크린샷 기능은 가는 획으로 저장해서 둘이 다르다.
# 위치·크기(14×15, 이름 첫 행 +1, 오른쪽 끝 x)는 같고 모양만 다르므로 두 템플릿을 모두 시도한다.
PCT_ROWS_BOLD = ['001110000001000', '010011000011000', '110011000110000', '110011000110000', '110011001100000',
                 '010011001100000', '001110011000000', '000000010001110', '000000110011011', '000001100110001',
                 '000001100110001', '000011000110001', '000011000011011', '000110000001110']
PCT_MASKS = [("bold", np.array([[c == "1" for c in r] for r in PCT_ROWS_BOLD])),     # 실제 화면 (먼저)
             ("thin", np.array([[c == "1" for c in r] for r in PCT_ROWS]))]           # 게임 스크린샷
PCT_MASK = PCT_MASKS[1][1]
PCT_DY = 1                  # "%" 마스크 첫 행 = 이름 글자 첫 행 + 1
NAME_W = 496                # "%" 오른쪽 끝 x − 이름 왼쪽 x
PCT_MAX_DIFF = 2
WHITE_MIN = 250             # strokes.py 와 같은 기준. 스크린샷은 255 지만 dxcam 캡처는 250~254 가 나올 수 있다

ICON = 14                   # 프레임 포함 아이콘 한 변
INNER = 12
PITCH = 18
STRIP_DY = -45              # 프레임 첫 행 = 이름 첫 행 − 45
STRIP_DX = -5               # 첫 칸 프레임 왼쪽 = 이름 왼쪽(text_x, 가는 글꼴 기준 계산값) − 5. 실측 16프레임 모두 동일
LABEL_DY = -27              # 라벨 창 첫 행 (글자는 −26..−20, 위아래 1행 여유)
LABEL_H = 9
LABEL_DX = 1                # 라벨 글자 왼쪽 = 프레임 왼쪽 + 1
LABEL_W = 15
MAX_SLOTS = 27
DIM_MAX = 120               # 아이콘 최대 채널이 이 미만이면 만료 직전 깜빡임 (정상 ≥ 200, 깜빡임 ≤ 64)
FRAME_DARK = 50             # 테두리 픽셀(체크무늬 0~41)로 볼 최대 밝기
FRAME_RATIO = 0.75          # 테두리 52px 중 어두운 비율 최소
ICON_MIN_CORR = 0.95        # 같은 아이콘으로 볼 내부 12×12 정규화 상관. 다른 아이콘끼리 최대 0.915 (노랑 검 vs 분홍 검)
ICON_MIN_CORR_STACK = 0.85  # icons.json 에서 tags 에 "stack" 이 있는 아이콘: 스택 수 숫자만 바뀌는 변형(실측 0.89~0.93)도 같은 것으로
ICON_MIN_CORR_DIM = 0.85    # 어둡게/반투명하게 사라지는 프레임(최대 채널 <200): 배경과 섞여 상관이 떨어진다(실측 0.84~0.90). 2위와 0.05 이상 차이 날 때만
FADE_MAX = 200
BLINK_GAINS = tuple(np.concatenate([np.arange(0.15, 1.0, 0.05), np.arange(1.0, 2.6, 0.1)]).round(2))
# 만료 직전 깜빡임은 어둡게(~25%)도, 밝게(~145%, 255 에서 잘림)도 그려진다 → 템플릿을 k 배 후 clip 한 것과 비교


# ---- 화면 변형별 치수 ----
# 위 상수는 UI 100% (4K). UI 150% 마비옛체는 실측값 (연속 저장 55장, 글라스 기브넨):
#   '%' 17×17 (전 프레임 동일), 이름 첫 행 +1. 띠 칸: 주황 바깥 테두리 24, 그 안 어두운 테두리 상자 20 (바깥+2), 그림 18×18 (바깥+3)
#   = 같은 그림을 1.5배. 피치 27. 테두리 상자 위 = 이름 첫 행 −67, 라벨 글자 −39..−29 (부드러운 글꼴), 패널 위 테두리 −21.
# 나눔고딕 150% 는 게임 버그로 라벨의 'M' 이 안 그려져 "4"(분)와 "4"(초)를 가를 수 없음 → 보스 디버프 미지원.
PCT_150_MABI = ['01111100000000000', '11101110000110000', '11000110000110000', '10000110001110000', '11000110011100000',
                '11000110011000000', '11111110111000000', '01111101110000000', '00000001100011000', '00000011101111110',
                '00000011001100111', '00000111011000011', '00001110011000011', '00001100011000011', '00011100001100011',
                '00001000001111110', '00000000000111100']


@dataclass(frozen=True)
class Geom:
    pct_masks: tuple            # ((style, bool 마스크), ...)
    pct_dy: int
    name_w: int
    icon: int                   # 어두운 테두리 상자 한 변
    inner: int                  # 그림 한 변 (캡처 크기)
    inner_off: int              # 상자 왼쪽 위 → 그림 왼쪽 위
    pitch: int
    strip_dy: int
    strip_dx: int
    label_dy: int
    label_h: int
    label_dx: int
    label_w: int
    panel_dy: int
    name_rows: int              # name_key 에 쓰는 이름 글자 행 수
    name_cols: int
    gap: int                    # 테두리 없는 아이콘 판정 때 왼쪽 간격 폭
    icon_min_corr: float        # 12×12 로 줄여 비교할 때 같은 아이콘 기준
    icon_margin: float          # 2위와 이만큼은 차이 (0 = 안 봄)
    scaled: bool                # 그림을 12×12 로 줄여 라이브러리와 비교하는가


GEOMS = {
    "100": Geom(tuple(PCT_MASKS), PCT_DY, NAME_W, ICON, INNER, 1, PITCH, STRIP_DY, STRIP_DX,
                LABEL_DY, LABEL_H, LABEL_DX, LABEL_W, -14, 17, 260, 4,
                ICON_MIN_CORR, 0.0, False),
    "150_mabi": Geom((("bold", np.array([[c == "1" for c in r] for r in PCT_150_MABI])),), 1, 750, 20, 18, 1, 27, -67, -5,
                     -41, 15, 0, 26, -21, 26, 390, 6,
                     # 12×12 로 줄이면 게임의 확대와 달라 같은 아이콘도 0.78~0.94, 2위(다른 아이콘)는 최대 0.61, 차이 최소 0.27
                     0.75, 0.25, True),
}


def geom() -> "Geom | None":
    """현재 화면 변형의 보스 바 치수. 지원 안 하는 변형(나눔고딕 150%)이면 None → 보스 디버프 끔."""
    return GEOMS.get(screen.current().key)


@dataclass
class Anchor:
    text_x: int             # 이름 글자 왼쪽 x (영역 기준). 굵은 글꼴이면 4px 더 왼쪽이지만 띠 스캔 중심으로만 쓴다
    text_y: int             # 이름 글자 첫 행
    pct_x1: int             # "%" 오른쪽 끝 x (포함)
    style: str = "bold"     # "bold"(실제 화면) | "thin"(게임 스크린샷)


@dataclass
class Slot:
    index: int
    x: int                  # 프레임 왼쪽 (영역 기준)
    y: int                  # 프레임 위
    icon: np.ndarray        # 내부 12×12 BGR
    label_img: np.ndarray   # 라벨 창 BGR (LABEL_H × LABEL_W)
    label: str = ""         # "4M", "40", "" (없음), "?" (모르는 글자)
    seconds: int | None = None
    icon_id: str | None = None   # IconLib 키. 모르면 None


@dataclass
class BarRead:
    anchor: Anchor | None
    slots: list[Slot] = field(default_factory=list)
    strip: bool = False             # 디버프 띠 패널이 있는 보스인가 (아이콘이 0개여도 True 일 수 있음)

    @property
    def present(self) -> bool:
        return self.anchor is not None

    @property
    def has_strip(self) -> bool:
        return self.strip


# ---------------------------------------------------------------- 바 찾기
def _white(bgr):
    return bgr.min(axis=2) >= WHITE_MIN


def find_bar(region_bgr, search=None) -> Anchor | None:
    """영역 안에서 "%" 글자를 찾아 anchor 를 돌려준다. search=(x, y, w, h) 로 탐색 범위를 좁힐 수 있다."""
    r = find_bar_diag(region_bgr, search)
    return r[0]


def find_bar_diag(region_bgr, search=None):
    """(anchor|None, 최소 차이 픽셀 수, (x, y)) — 못 찾을 때 왜 못 찾는지 보려고."""
    g = geom()
    if g is None:
        return None, 10 ** 6, (0, 0)
    w = _white(region_bgr).astype(np.uint8)
    ox = oy = 0
    if search is not None:
        x, y, ww, hh = search
        w = w[y:y + hh, x:x + ww]; ox, oy = x, y
    w = np.ascontiguousarray(w)
    best = None
    for style, mask in g.pct_masks:
        th, tw = mask.shape
        if w.shape[0] < th or w.shape[1] < tw:
            continue
        # 정확 일치 = 차이 픽셀 수. SQDIFF on 0/1 images == 다른 픽셀 수
        res = cv2.matchTemplate(w, mask.astype(np.uint8), cv2.TM_SQDIFF)
        _, _, loc, _ = cv2.minMaxLoc(res)
        y0, x0 = loc[1], loc[0]
        diff = int(res[y0, x0])
        if best is None or diff < best[0]:
            best = (diff, x0, y0, style, tw)
    if best is None:
        return None, 10 ** 6, (0, 0)
    diff, x0, y0, style, tw = best
    if diff > PCT_MAX_DIFF:
        return None, diff, (x0 + ox, y0 + oy)
    pct_x1 = x0 + tw - 1 + ox
    text_y = y0 - g.pct_dy + oy
    return Anchor(text_x=pct_x1 - g.name_w, text_y=text_y, pct_x1=pct_x1, style=style), diff, (x0 + ox, y0 + oy)


def name_key(region_bgr, anchor: Anchor) -> str:
    """보스 이름 글자(흰 마스크)의 해시. 같은 보스는 프레임이 달라도 같은 값 (렌더링이 픽셀 단위로 같다).
    이름은 왼쪽 정렬, 퍼센트는 오른쪽 정렬이라 왼쪽 260px 만 본다 (퍼센트 숫자는 계속 바뀌므로 제외)."""
    import hashlib
    g = geom() or GEOMS["100"]
    x0 = max(0, anchor.text_x - 8)
    m = _white(region_bgr[anchor.text_y:anchor.text_y + g.name_rows, x0:x0 + g.name_cols])
    return hashlib.sha1(np.packbits(m).tobytes()).hexdigest()[:12]


# ---------------------------------------------------------------- 띠 찾기
PANEL_DY = -14              # 띠 있는 보스: 바 위 테두리(어두운 1행)가 이름 첫 행 −14. 띠 없는 구형 보스는 −18 (바가 더 높다)


def has_strip_panel(region_bgr, anchor: Anchor) -> bool:
    """실측 23프레임: 띠 보스는 이름 −14 행이 전부 어둡고(1.00), 띠 없는 보스(제바흐)는 0.00."""
    g = geom() or GEOMS["100"]
    y = anchor.text_y + g.panel_dy
    if y < 2:
        return False
    x0, x1 = max(0, anchor.text_x - 10), anchor.pct_x1 + 10
    row = region_bgr[y, x0:x1]
    if row.size == 0:
        return False
    if not g.scaled:
        return float((row.max(axis=1) < 40).mean()) >= 0.9
    # UI 150%: 위 테두리가 반투명이라 바닥이 밝으면 48 까지 밝아진다 (실측 19~48). 절대값 대신 '위 패널·아래 바보다 확실히 어두운가'
    med = lambda yy: float(np.median(region_bgr[yy, x0:x1].max(axis=1)))
    m, above, below = med(y), med(y - 2), med(y + 1)
    return m < 90 and m < 0.75 * min(above, below)

def _ring_dark_ratio(reg, x, y):
    n = (geom() or GEOMS["100"]).icon
    box = reg[y:y + n, x:x + n]
    if box.shape[0] != n or box.shape[1] != n:
        return 0.0
    m = box.max(axis=2) < FRAME_DARK
    ring = np.concatenate([m[0, :], m[-1, :], m[1:-1, 0], m[1:-1, -1]])
    return float(ring.mean())


def _gray(bgr):
    return bgr.max(axis=2)


def _has_content(icon):
    """내부가 거의 단색(검은 배경, 보라 바닥 등)이면 아이콘이 아니다. 색 편차가 아니라 밝기 편차로 본다."""
    return float(_gray(icon).std()) > 12


def _label_ok(region_bgr, x, ly, lib) -> bool:
    """아래에 읽히는 라벨(숫자/M)이 있는가. 흰 픽셀 수만 세면 흰 얼음 바닥에서 오검출 → 글자 매칭까지 요구."""
    g = geom() or GEOMS["100"]
    lab = region_bgr[ly:ly + g.label_h, x + g.label_dx:x + g.label_dx + g.label_w]
    if not lab.size or int(_white(lab).sum()) < 5:
        return False
    glyphs = segment(lab)
    return bool(glyphs) and all(lib.match(g.mask) is not None for g in glyphs) if lib is not None else bool(glyphs)


def _slot_score(region_bgr, x, y, ly, lib=None) -> float:
    """칸에 아이콘이 있을 점수. 0 = 없음.
    - 라벨(흰 글자)이 아래에 있으면 확실 (라벨은 아이콘 아래에만 그려진다. 아주 어둡게 깜빡이는 프레임도 라벨은 남는다)
    - 테두리가 어둡고 내부에 밝기 편차가 있으면 아이콘
    - 테두리 없는 아이콘(파란 X 검): 14×14 전체가 밝고 편차가 큼. 단 왼쪽 4px 간격은 패널(어두움)이어야 한다 (밝은 바닥 오검출 방지)"""
    g = geom() or GEOMS["100"]
    if x + g.icon > region_bgr.shape[1] or x < 0:
        return 0.0
    box = region_bgr[y:y + g.icon, x:x + g.icon]
    inner = box[g.inner_off:g.inner_off + g.inner, g.inner_off:g.inner_off + g.inner]
    ring = _ring_dark_ratio(region_bgr, x, y)
    if _label_ok(region_bgr, x, ly, lib):
        return 2.0 + ring
    if ring >= FRAME_RATIO and _has_content(inner) and int(inner.max()) >= 130:
        return 1.0 + ring
    gb = _gray(box)
    if float(gb.std()) > 40 and int(gb.max()) >= 200:
        gap = _gray(region_bgr[y:y + g.icon, max(0, x - g.gap):x])
        if gap.size and float(gap.mean()) < 130:
            return 1.0
    return 0.0


def find_slots(region_bgr, anchor: Anchor, lib: GlyphLib | None = None) -> list[Slot]:
    g = geom() or GEOMS["100"]
    y = anchor.text_y + g.strip_dy
    ly = anchor.text_y + g.label_dy
    if y < 0 or y + g.icon > region_bgr.shape[0]:
        return []
    # 띠 시작 x 는 실측상 항상 이름 왼쪽 + STRIP_DX. ±2 만 허용하되, 칸 '수'가 아니라 칸당 '평균 점수'로 고른다
    # (어긋난 위치에선 테두리 점수가 낮고, 어두운 배경이 칸으로 더 잡혀 수는 오히려 많았다). 동점이면 기대 위치.
    expect = anchor.text_x + g.strip_dx
    best_x, best_n, best_score = None, 0, 0.0
    for dx in (0, -1, 1, -2, 2):
        x0 = expect + dx
        n, score = 0, 0.0
        for i in range(MAX_SLOTS):
            sc = _slot_score(region_bgr, x0 + i * g.pitch, y, ly, lib)
            if sc <= 0:
                break
            n += 1; score += sc
        mean = score / n if n else 0.0
        if mean > best_score + 1e-6:
            best_x, best_n, best_score = x0, n, mean
    if best_n == 0:
        return []
    out = []
    for i in range(best_n):
        x = best_x + i * g.pitch
        o = g.inner_off
        icon = region_bgr[y + o:y + o + g.inner, x + o:x + o + g.inner].copy()
        if g.scaled:          # UI 150%: 같은 그림의 1.5배 → 라이브러리(12×12)와 비교·표시하려고 줄인다
            icon = cv2.resize(icon, (INNER, INNER), interpolation=cv2.INTER_AREA)
        lab = region_bgr[ly:ly + g.label_h, x + g.label_dx:x + g.label_dx + g.label_w].copy()
        out.append(Slot(i, x, y, icon, lab))
    return out


# ---------------------------------------------------------------- 라벨
def read_label(label_img, lib: GlyphLib) -> tuple[str, int | None]:
    """'4M' → 240, '40' → 40, '' → None(라벨 없음), '?…' → None(모르는 글자)."""
    glyphs = segment(label_img)
    if not glyphs:
        return "", None
    text = "".join(lib.match(g.mask) or "?" for g in glyphs)
    if "?" in text:
        return text, None
    if text.endswith("M") and text[:-1].isdigit():
        return text, int(text[:-1]) * 60
    if text.isdigit():
        return text, int(text)
    return text, None


# ---------------------------------------------------------------- 아이콘 라이브러리
class IconLib:
    """디버프 아이콘 12×12 템플릿. folder/<id>.png + folder/icons.json ({id: {"name", "tags"}}).
    렌더링이 픽셀 단위로 같아서 평균 절대차로 충분. 모르는 아이콘은 unknown_dir 에 저장해 나중에 이름 붙인다."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.meta: dict[str, dict] = {}
        self.items: dict[str, np.ndarray] = {}
        self._bank_cache = None
        self.load()

    def load(self):
        self.meta, self.items = {}, {}
        mf = self.folder / "icons.json"
        if mf.exists():
            self.meta = json.loads(mf.read_text(encoding="utf-8"))
        for p in self.folder.glob("*.png"):
            img = cv2.imread(str(p))
            if img is not None and img.shape[:2] == (INNER, INNER):
                self.items[p.stem] = img
                self.meta.setdefault(p.stem, {"name": "", "tags": []})

    def save_meta(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "icons.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _norm(icon):
        a = icon.astype(np.float32).ravel()
        a -= a.mean()
        n = float(np.sqrt((a * a).sum()))
        return a / n if n > 1e-6 else a

    def _bank(self):
        """아이콘별로 (원본 + 밝기 변형 clip(k·tmpl)) 을 정규화해 쌓은 행렬. 매칭은 내적 한 번."""
        if self._bank_cache is None or set(self._bank_cache) != set(self.items):
            self._bank_cache = {}
            for k, m in self.items.items():
                t = m.astype(np.float32)
                rows = [self._norm(m)] + [self._norm(np.clip(g * t, 0, 255)) for g in BLINK_GAINS]
                self._bank_cache[k] = np.stack(rows)
        return self._bank_cache

    def similarity(self, icon, key) -> float:
        """icon 이 key 아이콘(또는 그 밝기 변형)인지: 정규화 상관의 최댓값."""
        return float((self._bank()[key] @ self._norm(icon)).max())

    def match(self, icon) -> tuple[str | None, float]:
        """(id, 유사도). 밝기에 무관 (만료 직전엔 아이콘이 어둡게/밝게 깜빡인다)."""
        a = self._norm(icon)
        best, best_c, second = None, -1.0, -1.0
        for k, bank in self._bank().items():
            c = float((bank @ a).max())
            if c > best_c:
                best, best_c, second = k, c, best_c
            elif c > second:
                second = c
        if best is None:
            return None, best_c
        g = geom() or GEOMS["100"]
        if g.scaled:          # UI 150%: 줄인 그림이라 기준을 낮추되 2위와의 차이로 확인
            if best_c >= g.icon_min_corr and best_c - second >= g.icon_margin:
                return best, best_c
            return None, best_c
        if best_c >= (ICON_MIN_CORR_STACK if self.is_stack(best) else ICON_MIN_CORR):
            return best, best_c
        if int(icon.max()) < FADE_MAX and best_c >= ICON_MIN_CORR_DIM and best_c - second >= 0.05:
            return best, best_c
        return None, best_c

    def is_stack(self, k) -> bool:
        return "stack" in (self.meta.get(k) or {}).get("tags", [])

    @staticmethod
    def key_of(icon) -> str:
        import hashlib
        return hashlib.sha1(icon.tobytes()).hexdigest()[:10]

    @staticmethod
    def is_dim(icon) -> bool:
        """만료 직전 깜빡임(약 25% 밝기). 정상 아이콘은 최대 채널 ≥ 200, 깜빡일 땐 ≤ 64."""
        return int(icon.max()) < DIM_MAX

    @staticmethod
    def is_bright_blink(icon) -> bool:
        """밝게 깜빡이는 프레임(과다 노출). 정상 아이콘도 255 가 있으니 '255 인 픽셀이 25% 이상'으로만 본다."""
        return float((icon.max(axis=2) >= 255).mean()) > 0.25

    def add(self, icon, name="", tags=()) -> str:
        """깜빡이는(어두운) 변형은 등록하지 않는다 (호출 전 is_dim 확인)."""
        k = self.key_of(icon)
        self.folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(self.folder / f"{k}.png"), icon)
        self.items[k] = icon.copy()
        self.meta[k] = {"name": name, "tags": list(tags)}
        self.save_meta()
        return k

    def name(self, k) -> str:
        return (self.meta.get(k) or {}).get("name") or k


# ---------------------------------------------------------------- 한 번에
def read_bar(region_bgr, lib: GlyphLib, icons: IconLib | None = None, search=None) -> BarRead:
    if geom() is None:
        return BarRead(None)                  # 지원 안 하는 화면 변형
    a = find_bar(region_bgr, search)
    if a is None:
        return BarRead(None)
    strip = has_strip_panel(region_bgr, a)
    g = geom()
    # UI 150%: 반투명 패널이라 이펙트·밝은 바닥에서 패널 판정이 가끔 빠진다 → 칸은 항상 찾아 보고, 칸이 있으면 띠 있음
    slots = find_slots(region_bgr, a, lib) if (strip or g.scaled) else []
    if slots:
        strip = True
    for s in slots:
        s.label, s.seconds = read_label(s.label_img, lib)
        if icons is not None:
            s.icon_id, _ = icons.match(s.icon)
    return BarRead(a, slots, strip)