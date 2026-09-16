"""
라이브 자동 저장 프레임 (300x550 상태창 크롭) 회귀 테스트.
어두운 맵에서 검출한 고정 레이아웃으로, 각 프레임에서 12행이 유지되고 시간이 정확히 읽히는지.
배경: 밝은 돌바닥+붉은 이펙트, 밝은 회색(안개), 어두움, 밝은 돌바닥, 마을(혼합).
"""
from pathlib import Path
import cv2
import pytest

from core.rows import detect_rows
from core.status import parse_rows
from core.digits import GlyphLib, read_time

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures"
LIB = ROOT / "assets" / "glyphs.json"
BASE = FIX / "live_dark.png"                     # 레이아웃 검출용 (어두운 배경)

FRAMES = {   # 파일: {행: 시간(초)}  — 활성 행의 시간만
    "live_dark.png":       {3: 167},             # 2분 47초
    "live_fog.png":        {3: 179},             # 2분 59초
    "live_stone.png":      {3: 148},             # 2분 28초
    "live_stone_red.png":  {2: 143, 3: 122},     # 2분 23초 / 2분 2초
    "live_village.png":    {2: 157, 3: 136},     # 2분 37초 / 2분 16초
}
pytestmark = pytest.mark.skipif(not (BASE.exists() and LIB.exists()), reason="fixture 없음")


@pytest.fixture(scope="module")
def layout():
    base = cv2.imread(str(BASE))
    L = detect_rows(base)
    assert L is not None
    pinned = sorted(L.sections[0])
    L.rows = [L.rows[i] for i in pinned]
    L.sections = [list(range(len(L.rows)))]
    L.widen(base.shape[1])
    assert len(L.rows) == 12
    return L


@pytest.mark.parametrize("name, truth", FRAMES.items())
def test_frame(layout, name, truth):
    p = FIX / name
    if not p.exists():
        pytest.skip(f"{name} 없음")
    img = cv2.imread(str(p))
    lib = GlyphLib.load(LIB)
    states = parse_rows(img, layout)
    assert [s.index for s in states] == list(range(12))      # 배경이 뭐든 행은 안 빠진다
    got = {}
    for s in states:
        if s.time_img is None:
            continue
        r = read_time(s.time_img, lib)
        if r.plausible:
            got[s.index] = r.seconds
    assert got == truth, got