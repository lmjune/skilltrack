"""4K 100% 보스 띠 — 2026-09-26 실사용 진단 프레임 (tests/fixtures/boss/0926/). 없으면 건너뜀.
1) 물풍선: 최대 채널이 전부 255 인 밝은 아이콘을 '빈칸'으로 봐서 띠 스캔이 멈춤 → 뒤의 야옹·모모가 '빠짐'
2) 밝은 바닥: 1px 어긋난 시작 위치가 앞 두 칸만 높은 점수로 뽑혀 14칸 중 2칸만 읽음"""
from pathlib import Path

import cv2
import pytest

from core import screen
from core.bossbar import IconLib, read_bar
from core.digits import GlyphLib
from core.paths import ASSETS

FIX = Path(__file__).parent / "fixtures" / "boss" / "0926"


def _read(name):
    p = FIX / name
    if not p.exists():
        pytest.skip(f"픽스처 없음: {p}")
    screen.set_screen("100")
    icons = IconLib(ASSETS / "boss_icons")
    r = read_bar(cv2.imread(str(p)), GlyphLib.load(ASSETS / "glyphs.json"), icons)
    return [(s.label, icons.name(s.icon_id) if s.icon_id else None) for s in r.slots]


def test_water_balloon_does_not_stop_scan():
    got = _read("20260926_170831_dropped.png")
    names = [n for _, n in got]
    assert names[:7] == ["물보깎", "마보깎", "뎀증", "미르", "데마", "물풍선", "야옹"], got
    assert "모모" in names and len(got) == 14, got


def test_bright_floor_keeps_expected_start():
    got = _read("20260926_170241_newicon.png")
    assert len(got) == 14, got
    assert [n for _, n in got][:2] == ["물보깎", "마보깎"] and got[5][1] == "물풍선", got
