"""시간 텍스트 읽기 테스트. fixtures/status1.png + assets/glyphs.json"""
from pathlib import Path
import cv2
import pytest

from core.rows import detect_rows
from core.status import parse_rows
from core.digits import GlyphLib, read_time, segment

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures" / "status1.png"
LIB = ROOT / "assets" / "glyphs.json"
pytestmark = pytest.mark.skipif(not (FIX.exists() and LIB.exists()), reason="fixture/glyphs 없음")

TRUTH = {2: 43, 3: 115, 4: 1535, 6: 186, 7: 0, 12: 2, 13: 115, 14: 186,
         15: 186, 16: 186, 17: 1535, 18: 1536, 19: 1536}


@pytest.fixture(scope="module")
def states():
    img = cv2.imread(str(FIX))
    crop = img[1230:1780, 2880:3220]
    return parse_rows(crop, detect_rows(crop))


def test_read_all_times(states):
    lib = GlyphLib.load(LIB)
    for s in states:
        if s.time_img is None:
            assert s.index not in TRUTH
            continue
        r = read_time(s.time_img, lib)
        assert r.seconds == TRUTH[s.index], (s.index, r.text)
        assert not r.unknown


def test_glyph_widths(states):
    """숫자 5px, 분/초 9px"""
    for s in states:
        if s.time_img is None:
            continue
        for g in segment(s.time_img):
            assert g.x1 - g.x0 in (5, 9)


def test_unknown_glyph_returns_none(states):
    lib = GlyphLib()   # 빈 라이브러리
    s = next(s for s in states if s.time_img is not None)
    r = read_time(s.time_img, lib)
    assert r.seconds is None and r.unknown