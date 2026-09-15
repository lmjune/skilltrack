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

MAX_DIFF = 3        # 같은 글자로 볼 최대 픽셀 차이


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


def _to_mask(img_bgr) -> np.ndarray:
    from core.strokes import stroke_masks
    w, g, r = stroke_masks(img_bgr)
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


class GlyphLib:
    def __init__(self):
        self.items: list[tuple[str, np.ndarray]] = []

    # ---- 저장/로드 ----
    def save(self, path):
        data = [{"label": l, "rows": ["".join("1" if v else "0" for v in r) for r in m]}
                for l, m in self.items]
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")

    @classmethod
    def load(cls, path):
        lib = cls()
        if Path(path).exists():
            for d in json.loads(Path(path).read_text(encoding="utf-8")):
                lib.items.append((d["label"], np.array([[c == "1" for c in r] for r in d["rows"]])))
        return lib

    # ---- 학습/매칭 ----
    def add(self, label: str, mask: np.ndarray):
        if self.match(mask) != label:
            self.items.append((label, mask.copy()))

    def match(self, mask: np.ndarray) -> str | None:
        best, best_d = None, MAX_DIFF + 1
        for label, m in self.items:
            if m.shape != mask.shape:
                continue
            d = int(np.count_nonzero(m != mask))
            if d < best_d:
                best, best_d = label, d
        return best

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
    text, unknown = "", []
    for g in glyphs:
        g.label = lib.match(g.mask)
        if g.label is None:
            unknown.append(g)
            text += "?"
        else:
            text += g.label
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