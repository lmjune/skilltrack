"""
상태창 행 검출 회귀 테스트. fixtures/status1.png (3840x2160, 버프 21개) 기준.
"""
from pathlib import Path
import cv2
import pytest

from core.rows import detect_rows

FIXDIR = Path(__file__).parent / "fixtures"
FIX = FIXDIR / "status1.png"
FIX_WHITE = FIXDIR / "status2_white.png"     # 눈밭(밝은 배경), 고정 12행만 있음
FIX_WOOD = FIXDIR / "status3_wood.png"       # 나무집(기둥 경계선이 패널을 가로지름), 고정 12행, 빨간 50초
FIX_WOOD2 = FIXDIR / "status4_wood2.png"     # 같은 장소 다른 순간, 흰 1분 25초, 패널 위에 '41%' 표시
pytestmark = pytest.mark.skipif(not FIX.exists(), reason="fixture 없음")

# 21개 행의 상단 y (절대 좌표). 12개 + 구분선 + 9개
TOPS = [1243, 1267, 1291, 1315, 1339, 1363, 1387, 1411, 1435, 1459, 1483, 1507,
        1541, 1565, 1589, 1613, 1637, 1661, 1685, 1709, 1733]


@pytest.fixture(scope="module")
def img():
    return cv2.imread(str(FIX))


def run(img, rect):
    x, y, w, h = rect
    L = detect_rows(img[y:y + h, x:x + w])
    if L is None:
        return None, []
    return L, [r.y + y for r in L.rows]


@pytest.mark.parametrize("rect, expect", [
    ((2880, 1230, 340, 550), TOPS),          # 딱 맞게
    ((2860, 1200, 400, 620), TOPS),          # 대충 크게
    ((2800, 1100, 500, 750), TOPS),          # 훨씬 크게 (위쪽 다른 UI 포함)
    ((2880, 1230, 340, 300), TOPS[:12]),     # 위쪽 섹션만
    ((2880, 1500, 340, 280), TOPS[11:]),     # 아래쪽 섹션 + 위 섹션 마지막 행
])
def test_rows(img, rect, expect):
    L, tops = run(img, rect)
    assert L is not None
    assert L.pitch == 24
    assert 14 <= L.icon_h <= 20
    assert len(tops) == len(expect), tops
    assert all(abs(a - b) <= 2 for a, b in zip(tops, expect)), tops


@pytest.mark.parametrize("rect", [
    (1500, 600, 400, 400),   # 아무것도 없는 곳
    (0, 0, 600, 110),        # 스킬바 (격자지 목록 아님)
    (845, 260, 180, 360),    # 펫 창
])
def test_not_a_list(img, rect):
    L, _ = run(img, rect)
    assert L is None


def test_sections_split_at_separator(img):
    L, tops = run(img, (2880, 1230, 340, 550))
    assert L.sections == [list(range(12)), list(range(12, 21))]
    assert all(abs(a - b) <= 2 for a, b in zip([r.y + 1230 for r in L.pinned], TOPS[:12]))


def test_single_section_when_only_top_visible(img):
    L, _ = run(img, (2880, 1230, 340, 300))
    assert len(L.sections) == 1 and len(L.pinned) == 12


@pytest.mark.skipif(not FIX_WHITE.exists(), reason="흰 배경 fixture 없음")
@pytest.mark.parametrize("rect", [(2880, 1230, 340, 550), (2860, 1200, 400, 620), (2800, 1100, 500, 750)])
def test_white_background(rect):
    img = cv2.imread(str(FIX_WHITE))
    L, tops = run(img, rect)
    assert L is not None and L.pitch == 24
    assert len(L.sections) == 1 and len(L.pinned) == 12
    assert all(abs(a - b) <= 2 for a, b in zip(tops, TOPS[:12])), tops


@pytest.mark.skipif(not FIX_WOOD.exists(), reason="나무집 fixture 없음")
@pytest.mark.parametrize("rect", [(2880, 1230, 340, 550), (2860, 1200, 400, 620), (2800, 1100, 500, 750)])
def test_wood_background_with_beam_edge(rect):
    img = cv2.imread(str(FIX_WOOD))
    L, tops = run(img, rect)
    assert L is not None and L.pitch == 24
    assert len(L.sections) == 1 and len(L.pinned) == 12
    assert all(abs(a - b) <= 2 for a, b in zip(tops, TOPS[:12])), tops


@pytest.mark.skipif(not FIX_WOOD2.exists(), reason="나무집2 fixture 없음")
@pytest.mark.parametrize("rect", [(2880, 1230, 340, 550), (2880, 1230, 340, 300), (2800, 1100, 500, 750)])
def test_wood2_ignores_ui_above_panel(rect):
    img = cv2.imread(str(FIX_WOOD2))
    L, tops = run(img, rect)
    assert L is not None and L.pitch == 24
    assert len(L.sections) == 1 and len(L.pinned) == 12, tops