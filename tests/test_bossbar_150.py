"""보스 바·디버프 띠 — UI 150% 마비옛체 (연속 저장, 글라스 기브넨).
픽스처: tests/fixtures/variants/boss_150_mabi/*.webp (win/snap.py F9, 영역 1400,1700,1050,320). 없으면 건너뜀.
나눔고딕 150% 는 게임이 라벨의 'M'(분)을 안 그려서 지원하지 않는다 (read_bar 가 항상 '바 없음')."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from core import screen
from core.bossbar import IconLib, read_bar
from core.digits import GlyphLib
from core.paths import ASSETS

FIX = Path(__file__).parent / "fixtures" / "variants" / "boss_150_mabi"


@pytest.fixture(autouse=True)
def reset_screen():
    yield
    screen.set_screen("100")


def _frames():
    return sorted([*FIX.glob("2*.webp"), *FIX.glob("2*.png")]) if FIX.exists() else []


def _libs():
    screen.set_screen("150_mabi")
    return GlyphLib.load(screen.boss_glyphs(), fuzzy=True), IconLib(ASSETS / "boss_icons")


def test_nanum_150_boss_disabled():
    screen.set_screen("150_nanum")
    img = np.zeros((320, 1050, 3), np.uint8)
    assert not read_bar(img, GlyphLib(), None).present


def test_every_frame_finds_bar_and_reads_all_labels():
    frames = _frames()
    if len(frames) < 10:
        pytest.skip("픽스처 없음")
    lib, icons = _libs()
    for f in frames:
        r = read_bar(cv2.imread(str(f)), lib, icons)
        assert r.present, f.name
        for s in r.slots:
            assert s.label == "" or s.seconds is not None, (f.name, s.index, s.label)


def test_last_frame_contents():
    """마지막 장: 물보깎·마보깎 25초, 뎀증·데마 2분, 붕파 0초, 야옹 9분, 공격력감소 25초, 모모 4분, 생명의역류(시간 없음)."""
    frames = _frames()
    if len(frames) < 10:
        pytest.skip("픽스처 없음")
    lib, icons = _libs()
    r = read_bar(cv2.imread(str(frames[-1])), lib, icons)
    got = [(s.label, icons.name(s.icon_id) if s.icon_id else None) for s in r.slots]
    assert got == [("25", "물보깎"), ("25", "마보깎"), ("2M", "뎀증"), ("2M", "데마"), ("0", "붕파"),
                   ("9M", "야옹"), ("25", "공격력감소"), ("4M", "모모"), ("", "생명의역류")], got


def test_second_labels_count_down():
    """초 라벨은 1초 간격 연속 저장에서 한 번에 0~2 씩만 줄어든다 (틀린 글자면 튄다)."""
    frames = _frames()
    if len(frames) < 10:
        pytest.skip("픽스처 없음")
    lib, icons = _libs()
    import re
    from datetime import datetime

    def stamp(f):
        return datetime.strptime(re.search(r"(\d{8}_\d{6}_\d{3})", f.name).group(1), "%Y%m%d_%H%M%S_%f").timestamp()

    prev = {}
    for f in frames:
        t = stamp(f)
        r = read_bar(cv2.imread(str(f)), lib, icons)
        for s in r.slots:
            if s.seconds is None or s.label.endswith("M") or s.icon_id is None:
                continue
            p = prev.get(s.icon_id)
            if p is not None and s.seconds <= p[0]:
                assert p[0] - s.seconds <= (t - p[1]) + 1.5, (f.name, icons.name(s.icon_id), p[0], s.seconds)
            prev[s.icon_id] = (s.seconds, t)
