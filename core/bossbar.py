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
BLINK_GAINS = tuple(np.concatenate([np.arange(0.15, 1.0, 0.05), np.arange(1.0, 2.6, 0.1)]).round(2))
# 만료 직전 깜빡임은 어둡게(~25%)도, 밝게(~145%, 255 에서 잘림)도 그려진다 → 템플릿을 k 배 후 clip 한 것과 비교


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
    w = _white(region_bgr).astype(np.uint8)
    ox = oy = 0
    if search is not None:
        x, y, ww, hh = search
        w = w[y:y + hh, x:x + ww]; ox, oy = x, y
    w = np.ascontiguousarray(w)
    best = None
    for style, mask in PCT_MASKS:
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
    text_y = y0 - PCT_DY + oy
    return Anchor(text_x=pct_x1 - NAME_W, text_y=text_y, pct_x1=pct_x1, style=style), diff, (x0 + ox, y0 + oy)


def name_key(region_bgr, anchor: Anchor) -> str:
    """보스 이름 글자(흰 마스크)의 해시. 같은 보스는 프레임이 달라도 같은 값 (렌더링이 픽셀 단위로 같다).
    이름은 왼쪽 정렬, 퍼센트는 오른쪽 정렬이라 왼쪽 260px 만 본다 (퍼센트 숫자는 계속 바뀌므로 제외)."""
    import hashlib
    x0 = max(0, anchor.text_x - 8)
    m = _white(region_bgr[anchor.text_y:anchor.text_y + 17, x0:x0 + 260])
    return hashlib.sha1(np.packbits(m).tobytes()).hexdigest()[:12]


# ---------------------------------------------------------------- 띠 찾기
PANEL_DY = -14              # 띠 있는 보스: 바 위 테두리(어두운 1행)가 이름 첫 행 −14. 띠 없는 구형 보스는 −18 (바가 더 높다)


def has_strip_panel(region_bgr, anchor: Anchor) -> bool:
    """실측 23프레임: 띠 보스는 이름 −14 행이 전부 어둡고(1.00), 띠 없는 보스(제바흐)는 0.00."""
    y = anchor.text_y + PANEL_DY
    if y < 0:
        return False
    row = region_bgr[y, max(0, anchor.text_x - 10):anchor.pct_x1 + 10]
    return row.size > 0 and float((row.max(axis=1) < 40).mean()) >= 0.9

def _ring_dark_ratio(reg, x, y):
    box = reg[y:y + ICON, x:x + ICON]
    if box.shape[0] != ICON or box.shape[1] != ICON:
        return 0.0
    m = box.max(axis=2) < FRAME_DARK
    ring = np.concatenate([m[0, :], m[-1, :], m[1:-1, 0], m[1:-1, -1]])
    return float(ring.mean())


def _has_content(icon):
    """내부가 거의 단색(검은 배경 등)이면 아이콘이 아니다."""
    return icon.std() > 12


def _has_label(region_bgr, x, ly):
    lab = region_bgr[ly:ly + LABEL_H, x + LABEL_DX:x + LABEL_DX + LABEL_W]
    return lab.size and int(_white(lab).sum()) >= 5


def _occupied(region_bgr, x, y, ly):
    """칸에 아이콘이 있는가. 테두리가 어둡고 내부에 그림이 있어야 하며,
    어두운 배경이 우연히 통과하는 걸 막기 위해 '밝은 픽셀(≥90)이 있거나 아래에 라벨이 있어야' 한다
    (만료 직전 어둡게 깜빡이는 아이콘은 최대 60~76 이지만 항상 초 라벨이 붙어 있다)."""
    if x + ICON > region_bgr.shape[1]:
        return False
    inner = region_bgr[y + 1:y + 1 + INNER, x + 1:x + 1 + INNER]
    if _ring_dark_ratio(region_bgr, x, y) >= FRAME_RATIO:
        return _has_content(inner) and (int(inner.max()) >= 90 or _has_label(region_bgr, x, ly))
    # 테두리가 없는 아이콘도 있다 (파란 X 검: 14×14 전체가 그림). 띠 뒤는 어두운 균일 패널이라
    # '내부가 확실한 그림'이면 칸으로 본다.
    box = region_bgr[y:y + ICON, x:x + ICON]
    return float(box.std()) > 40 and int(box.max()) >= 200


def find_slots(region_bgr, anchor: Anchor) -> list[Slot]:
    y = anchor.text_y + STRIP_DY
    ly = anchor.text_y + LABEL_DY
    if y < 0 or y + ICON > region_bgr.shape[0]:
        return []
    # 띠 시작 x 는 실측 23프레임 전부 이름 왼쪽 + STRIP_DX. 어두운 배경에선 엉뚱한 x 에서도 테두리 검사가 통과하고
    # 칸 수가 더 많이 나오기도 해서(잘린 아이콘이 등록되는 원인) 스캔하지 않고 ±2 만 허용한다.
    expect = anchor.text_x + STRIP_DX
    best_x, best_n = None, 0
    for dx in (0, -1, 1, -2, 2):
        x0 = expect + dx
        if x0 < 0:
            continue
        n = 0
        for i in range(MAX_SLOTS):
            if not _occupied(region_bgr, x0 + i * PITCH, y, ly):
                break
            n += 1
        if n > best_n:
            best_x, best_n = x0, n
    if best_n == 0:
        return []
    out = []
    for i in range(best_n):
        x = best_x + i * PITCH
        icon = region_bgr[y + 1:y + 1 + INNER, x + 1:x + 1 + INNER].copy()
        lab = region_bgr[ly:ly + LABEL_H, x + LABEL_DX:x + LABEL_DX + LABEL_W].copy()
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
        best, best_c = None, -1.0
        for k, bank in self._bank().items():
            c = float((bank @ a).max())
            if c > best_c:
                best, best_c = k, c
        if best is not None and best_c >= (ICON_MIN_CORR_STACK if self.is_stack(best) else ICON_MIN_CORR):
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
    a = find_bar(region_bgr, search)
    if a is None:
        return BarRead(None)
    strip = has_strip_panel(region_bgr, a)
    slots = find_slots(region_bgr, a) if strip else []
    for s in slots:
        s.label, s.seconds = read_label(s.label_img, lib)
        if icons is not None:
            s.icon_id, _ = icons.match(s.icon)
    return BarRead(a, slots, strip)