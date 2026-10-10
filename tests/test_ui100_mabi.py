"""UI 배율 조정 켬 + 100% + 마비옛체 (4K 실측): 상태창 시간·보스 띠·투아림·자원 막대.

이 모드는 크기는 기본 100% 와 같지만 글자가 작은 부드러운 글꼴이라 기본 글자 세트로는 하나도 안 읽혔다.
"""
import json
from pathlib import Path

import cv2
import pytest

from core import screen

FIX = Path(__file__).parent / "fixtures" / "ui100_mabi"


@pytest.fixture
def variant():
    screen.set_screen("100_mabi")
    yield screen.current()
    screen.set_screen("100")


@pytest.mark.parametrize("folder", ["status", "status_qhd", "status_29m"])
def test_status_times(variant, folder):
    """시간 글자: 다른 행(세로 반 픽셀 위치가 다름), 빨간 글자(1분 미만)까지 전부 읽는다."""
    from core.digits import GrayLib, read_time
    from core.rows import detect_rows
    from core.status import parse_rows
    if not (FIX / folder / "truth.json").exists():
        pytest.skip("fixture 없음")
    T = json.loads((FIX / folder / "truth.json").read_text(encoding="utf-8"))
    lib = GrayLib.load(variant.glyphs)
    layouts = []
    for b in T["bases"]:
        img = cv2.imread(str(FIX / folder / b))
        L = detect_rows(img)
        assert L is not None and screen.pitch_matches(L.pitch)
        L.widen(img.shape[1]); layouts.append((b, L))
    wrong, n = [], 0
    for name, rows in T["times"].items():
        L = [lay for b, lay in layouts if b <= name or b == layouts[0][0]][-1]
        st = {s.index: s for s in parse_rows(cv2.imread(str(FIX / folder / name)), L)}
        for r, want in rows.items():
            n += 1
            got = read_time(st[int(r)].time_img, lib)
            if got.text != want or got.seconds is None:
                wrong.append((name, r, want, got.text))
    assert n >= 15 and not wrong, wrong


@pytest.mark.skipif(not (FIX / "boss" / "truth.json").exists(), reason="fixture 없음")
def test_boss_strip(variant):
    """보스 바(부드러운 '%')를 찾고, 띠 칸·아이콘·남은 시간 라벨(4M, 40 …)을 읽는다. 4K 12장 + QHD 5장."""
    from core.bossbar import IconLib, read_bar
    from core.digits import GrayLib
    from core.paths import ASSETS
    truth = json.loads((FIX / "boss" / "truth.json").read_text(encoding="utf-8"))
    lib = GrayLib.load(screen.boss_glyphs())
    icons = IconLib(ASSETS / "boss_icons")
    wrong = []
    for name, want in truth.items():
        r = read_bar(cv2.imread(str(FIX / "boss" / name)), lib, icons)
        assert r.present and r.strip, name
        got = [[icons.meta.get(s.icon_id, {}).get("name"), s.label] for s in r.slots]
        if got != want:
            wrong.append((name, want, got))
    assert not wrong, wrong[:2]
    # 보스 없는 화면 (마을)
    assert not read_bar(cv2.imread(str(FIX / "boss" / "20261010_065740_802.png")), lib, icons).present


@pytest.mark.skipif(not (FIX / "status_region_4k.png").exists(), reason="fixture 없음")
def test_rows_found_for_any_drag(variant):
    """흐린 아이콘이라 영역 폭이 몇 px 달라지면 아이콘 열이 끊겨 줄을 못 찾았다 (→ 감시 항목이 안 열림).
    상태창을 덮는 여러 드래그 영역 모두에서 17줄."""
    import itertools
    from core.rows import detect_rows
    img = cv2.imread(str(FIX / "status_region_4k.png"))
    bad = []
    for dx, dy, dw, dh in itertools.product((0, 6, 14, 20), (12, 26, 36), (0, 10, 20), (0, 20, 30)):
        L = detect_rows(img[dy:img.shape[0] - dh, dx:img.shape[1] - dw])
        if L is None or len(L.rows) != 17:
            bad.append(((dx, dy, dw, dh), None if L is None else len(L.rows)))
    assert not bad, bad


@pytest.mark.skipif(not (FIX / "status_region_qhd.webp").exists(), reason="fixture 없음")
def test_text_start_when_icons_cut(variant):
    """QHD: 영역 왼쪽이 아이콘을 잘라 먹으면 이름 앞 글자가 아이콘 자리로 가고 텍스트가 이름 중간에서 시작했다
    (감시 항목 그림 '비바▌체'). 아이콘이 조금 잘리면 텍스트 시작은 이름 첫 글자 2px 앞,
    아이콘이 다 잘리면 (글자 열을 아이콘으로 잡는 대신) 못 찾음."""
    from core.rows import detect_rows
    img = cv2.imread(str(FIX / "status_region_qhd.webp"))
    name_x = 25                                    # 이 그림에서 이름 첫 획 열
    for dx in range(0, 16, 2):
        L = detect_rows(img[:, dx:])
        assert L is not None and len(L.rows) == 13, dx
        assert L.text_x == name_x - dx - 2, (dx, L.text_x)
    for dx in (18, 20, 22):
        assert detect_rows(img[:, dx:]) is None, dx
