"""
상태창 행 파싱 테스트. fixtures/status1.png 기준 (버프 21개).
"""
from pathlib import Path
import cv2
import numpy as np
import pytest

from core.rows import detect_rows
from core.status import parse_rows, fingerprint, fp_distance, fp_same

FIXDIR = Path(__file__).parent / "fixtures"
FIX = FIXDIR / "status1.png"
FIX_WHITE = FIXDIR / "status2_white.png"
FIX_WOOD = FIXDIR / "status3_wood.png"
FIX_WOOD2 = FIXDIR / "status4_wood2.png"
FIX_EFFECT = FIXDIR / "status5_effect.png"       # 붉은 마법진 이펙트가 패널을 덮음. 전장의 서곡 흰 2분 40초
FIX_NOEFFECT = FIXDIR / "status6_noeffect.png"   # 같은 자리, 이펙트 없음. 2분 1초
pytestmark = pytest.mark.skipif(not FIX.exists(), reason="fixture 없음")

NAMES = ["반신화", "엘레멘탈", "전장의서곡", "햄버닝", "공격력증가", "마나실드", "예리", "뇌신",
         "스매시", "별", "행진곡", "마이트", "이동속도", "햄아드", "역전", "재생", "신속",
         "음악버프", "연금술", "마법공격", "포션"]
DIMMED = {"반신화", "스매시", "별", "행진곡", "마이트"}
RED = {"전장의서곡", "뇌신", "이동속도"}
NO_TIME = {"반신화", "엘레멘탈", "마나실드", "스매시", "별", "행진곡", "마이트", "포션"}


@pytest.fixture(scope="module")
def states():
    img = cv2.imread(str(FIX))
    crop = img[1230:1780, 2880:3220]
    layout = detect_rows(crop)
    assert layout is not None and len(layout.rows) == 21
    return parse_rows(crop, layout)


def test_active_flags(states):
    for s in states:
        assert s.active == (NAMES[s.index] not in DIMMED), NAMES[s.index]


def test_time_flags(states):
    for s in states:
        assert s.has_time == (NAMES[s.index] not in NO_TIME), NAMES[s.index]
        assert s.red == (NAMES[s.index] in RED), NAMES[s.index]


def test_name_fingerprints_distinct(states):
    for a in states:
        for b in states:
            if a is not b:
                assert fp_distance(a.name_fp, b.name_fp) > 0.15, (NAMES[a.index], NAMES[b.index])


def test_same_icon_different_name(states):
    by = {NAMES[s.index]: s for s in states}
    assert fp_same(by["햄버닝"].icon_fp, by["햄아드"].icon_fp)
    assert not fp_same(by["햄버닝"].name_fp, by["햄아드"].name_fp)


@pytest.mark.skipif(not FIX_WHITE.exists(), reason="흰 배경 fixture 없음")
def test_fingerprint_same_across_backgrounds(states):
    """어두운 맵 / 눈밭 — 배경이 달라도, 활성/비활성이 달라도 같은 버프는 같은 지문."""
    img = cv2.imread(str(FIX_WHITE))
    crop = img[1230:1780, 2880:3220]
    white = parse_rows(crop, detect_rows(crop))
    assert len(white) == 12
    for a, b in zip(states[:12], white):
        assert fp_distance(a.name_fp, b.name_fp) <= 0.02, NAMES[a.index]


@pytest.mark.skipif(not FIX_WOOD.exists(), reason="나무집 fixture 없음")
def test_wood_frame(states):
    """나무집: 지문 일치, 빨간 50초 인식."""
    from core.digits import GlyphLib, read_time
    img = cv2.imread(str(FIX_WOOD))
    crop = img[1230:1780, 2880:3220]
    wood = parse_rows(crop, detect_rows(crop))
    assert len(wood) == 12
    for a, b in zip(states[:12], wood):
        assert fp_distance(a.name_fp, b.name_fp) <= 0.02, NAMES[a.index]
    by = {NAMES[s.index]: s for s in wood}
    # 나무 배경: 비활성 글자가 209 로 보임 (50% 투명 흰색). 255 인 전장의 서곡만 활성
    assert [s.index for s in wood if s.active] == [2]
    assert by["전장의서곡"].red and by["전장의서곡"].has_time
    lib = GlyphLib.load(Path(__file__).parent.parent / "assets" / "glyphs.json")
    assert read_time(by["전장의서곡"].time_img, lib).seconds == 50


@pytest.mark.skipif(not FIX_WOOD2.exists(), reason="나무집2 fixture 없음")
def test_wood2_frame(states):
    """나무집2: 지문 일치, 흰 '1분 25초' = 85초 (1분 이상이라 빨강 아님)."""
    from core.digits import GlyphLib, read_time
    img = cv2.imread(str(FIX_WOOD2))
    crop = img[1230:1780, 2880:3220]
    wood = parse_rows(crop, detect_rows(crop))
    assert len(wood) == 12
    for a, b in zip(states[:12], wood):
        assert fp_distance(a.name_fp, b.name_fp) <= 0.02, NAMES[a.index]
    by = {NAMES[s.index]: s for s in wood}
    assert by["전장의서곡"].has_time and not by["전장의서곡"].red
    lib = GlyphLib.load(Path(__file__).parent.parent / "assets" / "glyphs.json")
    assert read_time(by["전장의서곡"].time_img, lib).seconds == 85


@pytest.mark.parametrize("fix, seconds", [(FIX_EFFECT, 160), (FIX_NOEFFECT, 121)])
def test_effect_frames(states, fix, seconds):
    """붉은 이펙트가 패널 위를 덮어도: 지문 동일, 가짜 시간 없음, 진짜 시간은 읽힘, 비활성 행은 비활성."""
    if not fix.exists():
        pytest.skip("fixture 없음")
    from core.digits import GlyphLib, read_time
    img = cv2.imread(str(fix))
    crop = img[1230:1780, 2880:3220]
    rows = parse_rows(crop, detect_rows(crop))
    assert len(rows) == 12
    for a, b in zip(states[:12], rows):
        assert fp_distance(a.name_fp, b.name_fp) <= 0.02, NAMES[a.index]
    timed = [s for s in rows if s.has_time]
    assert [s.index for s in timed] == [2]
    assert not timed[0].red
    lib = GlyphLib.load(Path(__file__).parent.parent / "assets" / "glyphs.json")
    assert read_time(timed[0].time_img, lib).seconds == seconds
    assert all(not s.active for s in rows if s.index != 2)


def test_active_means_opaque_white(states):
    """활성 글자 획은 정확히 255. 비활성은 그보다 어둡다 (배경에 따라 127~245)."""
    from core.strokes import stroke_masks
    for s in states:
        w, g, _ = stroke_masks(s.name_img)
        px = s.name_img[w | g].min(axis=1)
        if s.active:
            assert (px >= 250).mean() > 0.9, NAMES[s.index]
        else:
            assert (px < 250).mean() > 0.9, NAMES[s.index]