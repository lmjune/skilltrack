"""
격자 검출 회귀 테스트.
fixtures/screen1.png : 스크린샷 (3840x2160)
fixtures/live.png    : dxcam 라이브 캡처 (같은 해상도, 테두리 렌더링이 미묘하게 다름)
실행: pytest tests/ -v
"""
from pathlib import Path
import cv2
import pytest

from core.grid import detect_grid_in

FIX = Path(__file__).parent / "fixtures"
IMAGES = [p for p in ("screen1.png", "live.png") if (FIX / p).exists()]
pytestmark = pytest.mark.skipif(not IMAGES, reason="fixture 없음")

BAR1_XS = [2, 46, 90, 134, 190, 234, 278, 322, 378, 422, 466, 510]
BAR2_XS = [622, 666, 710, 754, 810, 856, 898, 942, 998, 1042, 1086, 1130]
BAR_YS = [12, 61]


@pytest.fixture(scope="module", params=IMAGES)
def img(request):
    return cv2.imread(str(FIX / request.param))


def near(a, b, tol=2):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


@pytest.mark.parametrize("rect, xs, ys", [
    ((0, 0, 560, 100),   BAR1_XS,           BAR_YS),      # 딱 맞게
    ((30, 20, 600, 120), BAR1_XS[1:],       BAR_YS),      # 대충 + 첫 열 절반 잘림
    ((15, 8, 510, 85),   BAR1_XS[:11],      BAR_YS),      # 마지막 열 절반 잘림
    ((0, 0, 560, 50),    BAR1_XS,           BAR_YS[:1]),  # 한 줄만
    ((200, 0, 200, 100), BAR1_XS[4:9],      BAR_YS),      # 중간 일부
    ((90, 0, 50, 100),   BAR1_XS[2:3],      BAR_YS),      # 한 열만
    ((280, 12, 38, 38),  BAR1_XS[6:7],      BAR_YS[:1]),  # 슬롯 하나
    ((610, 0, 600, 100), BAR2_XS,           BAR_YS),      # 두 번째 바
    ((0, 0, 1230, 100),  BAR1_XS + BAR2_XS, BAR_YS),      # 두 바 동시
    ((0, 0, 900, 200),   BAR1_XS + BAR2_XS[:6], BAR_YS),  # 과하게 큰 드래그 (펫 창 포함)
])
def test_skill_bar(img, rect, xs, ys):
    g = detect_grid_in(img, rect)
    assert g is not None
    assert near(g.xs, xs), g.xs
    assert near(g.ys, ys), g.ys
    assert 38 <= g.w <= 41 and 38 <= g.h <= 41


def test_pet_window_different_ui(img):
    g = detect_grid_in(img, (845, 260, 180, 360))
    assert g is not None
    assert (g.cols, g.rows) == (4, 8)
    assert 38 <= g.w <= 41 and 38 <= g.h <= 41


def test_no_grid_returns_none(img):
    assert detect_grid_in(img, (1500, 300, 400, 200)) is None