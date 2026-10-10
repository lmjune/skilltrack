"""윈도우 HDR 꺼짐 + 부드러운 글꼴 (UI 150% 마비옛체·나눔고딕, UI 배율 조정 100% 마비옛체). 4K 실측.

HDR 이 켜져 있으면 캡처가 밝아져 글자가 255 로 꽉 차지만, 꺼지면 켜진 글자 200~250 / 꺼진 글자 ~127 이라
기존 기준(255)으론 상태창이 전부 '꺼짐', 보스 '%' 를 못 찾았다. screen.set_hdr(False) 일 때의 기준을 확인한다.
"""
import json
from pathlib import Path

import cv2
import pytest

from core import screen

FIX = Path(__file__).parent / "fixtures" / "sdr"
pytestmark = pytest.mark.skipif(not (FIX / "status_truth.json").exists(), reason="fixture 없음")


@pytest.fixture
def sdr():
    def use(var):
        screen.set_screen(var); screen.set_hdr(False)
    yield use
    screen.set_screen("100"); screen.set_hdr(True)


@pytest.mark.parametrize("var", ["100_mabi", "150_mabi", "150_nanum"])
def test_status_sdr(sdr, var):
    """켜짐/꺼짐 + 시간 (밝은 열 끊김으로 나눈 밝기 템플릿, assets/screens/<변형>/time_sdr.json)."""
    from core.digits import GrayLib, read_time
    from core.pixelwatch import make_site, read_site
    from core.rows import detect_rows
    from core.status import parse_rows
    sdr(var)
    T = json.loads((FIX / "status_truth.json").read_text(encoding="utf-8"))[var]
    lib = GrayLib.load(screen.sdr_glyphs())
    assert lib.mode == "bright"
    base = cv2.imread(str(FIX / T["base"]))
    L = detect_rows(base)
    assert L is not None and screen.pitch_matches(L.pitch)
    L.widen(base.shape[1])
    sites = {s.index: make_site(base, L.rows[s.index].text, s.name_range) for s in parse_rows(base, L) if s.name_range}
    wrong, n_time = [], 0
    for name, rows in T["frames"].items():
        img = cv2.imread(str(FIX / name))
        for s in parse_rows(img, L):
            act, t = rows[str(s.index)]
            got = read_time(s.time_img, lib).text if s.time_img is not None else None
            n_time += t is not None
            if bool(s.active) != act or got != t:
                wrong.append((name, s.index, act, t, s.active, got))
        if name == T["base"]:
            for i, st in sites.items():          # 획 자리 판정: 켜짐 255 대신 ≥185, 꺼짐 ~127
                want = "on" if rows[str(i)][0] else "off"
                assert read_site(img, st).state == want, (name, i)
    assert n_time >= 20 and not wrong, wrong


def test_hdr_on_keeps_old_rules(sdr):
    """HDR 켬(기본)이면 예전 기준 그대로: 같은 HDR 꺼짐 화면은 켜진 행을 못 본다 (= 설정이 실제로 갈린다)."""
    from core.rows import detect_rows
    from core.status import parse_rows
    T = json.loads((FIX / "status_truth.json").read_text(encoding="utf-8"))["150_nanum"]
    screen.set_screen("150_nanum"); screen.set_hdr(True)
    img = cv2.imread(str(FIX / T["base"]))
    L = detect_rows(img); L.widen(img.shape[1])
    assert not any(s.active for s in parse_rows(img, L))
    assert not screen.soft_sdr()
    screen.set_screen("100"); screen.set_hdr(False)
    assert not screen.soft_sdr()                  # 기본 UI 는 HDR 과 무관


@pytest.mark.skipif(not (FIX / "boss_truth.json").exists(), reason="fixture 없음")
def test_boss_sdr(sdr):
    """'%' (가장자리 안 보는 마스크), 라벨 (1.6배 밝게 → 기존 글자 세트), 아이콘 (브류/프라는 평균 색으로)."""
    from core.bossbar import IconLib, name_key, read_bar
    from core.digits import GlyphLib, GrayLib
    from core.paths import ASSETS
    truth = json.loads((FIX / "boss_truth.json").read_text(encoding="utf-8"))
    icons = IconLib(ASSETS / "boss_icons")
    keys = {}
    for name, want in truth.items():
        sdr(want["variant"]); sc = screen.current()
        lib = GrayLib.load(screen.boss_glyphs()) if sc.gray else GlyphLib.load(screen.boss_glyphs(), fuzzy=sc.fuzzy)
        img = cv2.imread(str(FIX / name))
        r = read_bar(img, lib, icons)
        assert r.present and r.strip, name
        assert [s.label for s in r.slots] == want["labels"], name
        assert [icons.meta.get(s.icon_id, {}).get("name") for s in r.slots] == want["icons"], name
        keys.setdefault(want["variant"], set()).add(name_key(img, r.anchor))
    assert all(len(v) == 1 for v in keys.values())     # 같은 보스는 같은 이름 해시 (체력이 줄어도)


@pytest.mark.skipif(not (FIX / "bars_truth.json").exists(), reason="fixture 없음")
def test_bars_sdr(sdr):
    """막대 숫자 대비 ±2%. UI 배율 조정 100% 스태미나는 HDR 꺼짐이면 기본 UI 색 (특수 규칙이면 늘 100% 로 읽혔다)."""
    from core.bars import read_bars
    truth = json.loads((FIX / "bars_truth.json").read_text(encoding="utf-8"))
    bad = []
    for name, t in truth.items():
        sdr(t["variant"])
        r = read_bars(cv2.imread(str(FIX / name)))
        for k, w in zip(("hp", "mp", "sp"), t["want"]):
            if r.get(k) is None or abs(r[k] - w) > 0.02:
                bad.append((name, k, w, r.get(k)))
    assert not bad, bad
