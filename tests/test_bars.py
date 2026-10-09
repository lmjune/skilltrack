"""생명력/마나/스태미나 막대: 색으로 비율 + 부족 알림 규칙."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from core.bars import BarCfg, BarTracker, event_text, read_bars

FIX = Path(__file__).parent / "fixtures" / "bars"


@pytest.mark.skipif(not (FIX / "partial.png").exists(), reason="fixture 없음")
def test_ratio_matches_numbers():
    r = read_bars(cv2.imread(str(FIX / "partial.png")))
    assert abs(r["hp"] - 4026 / 7056) < 0.01          # 화면 숫자 4026/7056
    assert abs(r["mp"] - 4981 / 5378) < 0.01
    assert abs(r["sp"] - 4195 / 4823) < 0.01


@pytest.mark.parametrize("name", ["full.png", "full_bright1.png", "full_bright2.png", "live_full.png"])
def test_full_bars(name):
    """꽉 찬 막대: 어둡고 단색인 그림과 밝고 그라데이션인 그림 둘 다 (같은 막대가 상태에 따라 다르게 그려짐)."""
    if not (FIX / name).exists():
        pytest.skip("fixture 없음")
    r = read_bars(cv2.imread(str(FIX / name)))
    assert all(r[k] is not None and r[k] >= 0.98 for k in ("hp", "mp", "sp")), r


LIVE = {   # 실제 게임 화면 (4K UI 100%, 밝은 그림) — 화면 숫자
    "live_s40.png": (6736 / 8808, 4616 / 5468, 4268 / 4853),
    "live_s44.png": (4497 / 7056, 4480 / 5378, 4148 / 4823),
    # 4K UI 150% 마비옛체 — 1px 테두리가 안쪽 색과 섞여 그려짐 (스태미나는 빨강 밝기로 가른다)
    "mabi150_s0.png": (1724 / 3413, 3055 / 3575, 1.0),
    "mabi150_s37.png": (791 / 2905, 2894 / 3400, 2221 / 2643),   # 생명력 경계가 숫자 밑
    # 4K UI 150% 나눔고딕
    "nanum150_s0.png": (2128 / 2905, 1.0, 1.0),
    "nanum150_s15.png": (1698 / 2905, 1.0, 2232 / 2643),
}


@pytest.mark.parametrize("name", sorted(LIVE))
def test_live(name):
    r = read_bars(cv2.imread(str(FIX / name)))
    for k, want in zip(("hp", "mp", "sp"), LIVE[name]):
        assert r[k] is not None and abs(r[k] - want) < 0.01, (k, r[k], want)


def _drain(img, key, pct):
    """찬 곳을 pct 까지로 줄인 화면 흉내: 경계 오른쪽 막대 색(글자 외곽선 포함)을 같은 밝기의 빈 색으로."""
    rows = {"hp": (4, 13, (228, 76, 163), (135, 46, 71), (255, 109, 237), (196, 65, 103))}[key]
    y0, y1, fb, eb, fi, ei = rows
    im = img[..., ::-1].astype(np.float32)
    b = 9 + round(102 * pct / 100)
    for y in range(y0, y1 + 1):
        f, e = (fb, eb) if y in (y0, y1) else (fi, ei)
        k = np.array(e, np.float32) / np.array(f, np.float32)
        seg = im[y, b:111]
        colour = (seg.max(axis=1) - seg.min(axis=1)) >= 30
        seg[colour] = np.clip(seg[colour] * k, 0, 255)
    return np.ascontiguousarray(im[..., ::-1].astype(np.uint8))


@pytest.mark.parametrize("pct", [50, 40, 30, 20, 10, 5])
def test_low_under_numbers(pct):
    """경계가 흰 숫자 밑에 있을 때 (예전엔 40% → 1% 로 읽어 거짓 위험 알림)."""
    full = cv2.imread(str(FIX / "live_full.png"))
    r = read_bars(_drain(full, "hp", pct))
    assert abs(r["hp"] * 100 - pct) <= 2, r


@pytest.mark.parametrize("name", ["live_s44.png", "mabi150_s37.png"])
def test_fade_never_reads_low(name):
    """화면 전환: 어두워지면 그대로, 하얗게 바래면 '모름' — 어느 쪽도 0% 같은 거짓 값이 아님."""
    img = cv2.imread(str(FIX / name)).astype(np.float32)
    want = LIVE[name]
    for k in (0.9, 0.6, 0.4):
        r = read_bars((img * k).astype(np.uint8))
        for key, w in zip(("hp", "mp", "sp"), want):
            assert r[key] is None or abs(r[key] - w) < 0.02, (k, key, r)
    for k in (0.2, 0.4, 0.6, 0.8):
        r = read_bars((img * (1 - k) + 255 * k).astype(np.uint8))
        for key, w in zip(("hp", "mp", "sp"), want):
            assert r[key] is None or r[key] >= w - 0.02, (k, key, r)


def test_no_bars():
    assert read_bars(np.zeros((40, 120, 3), np.uint8)) == {"hp": None, "mp": None, "sp": None}


def run(tr, seq, key="hp", dt=0.25):
    """seq: % 또는 None(못 읽음). 0.25초 간격."""
    out, t = [], 0.0
    for p in seq:
        out += [event_text(e) for e in tr.update({key: None if p is None else p / 100}, now=t)]
        t += dt
    return out


def test_low_needs_hold():
    """기준 이하가 1초 이어져야 알림 (화면 전환 순간 잘못 읽은 값 무시)."""
    tr = BarTracker({"hp": BarCfg(enabled=True, pct=30)})
    assert run(tr, [80, 80, 80, 5, 5, 5, 5, 80, 80, 80]) == []          # 잠깐 튄 값
    assert run(tr, [5, 5, 5, None, 5, 5, 5, None, 80]) == []             # 못 읽은 프레임 사이 (전환 중)
    assert run(tr, [20] * 8) == ["생명력 20%"]


def test_low_once_with_release_margin():
    tr = BarTracker({"hp": BarCfg(enabled=True, pct=30)})
    # 30 근처에서 출렁여도 한 번, 35 이상 회복해야 다시
    seq = [80] * 3 + [28] * 8 + [31, 29, 33, 30] * 3 + [36] * 4 + [25] * 8
    assert run(tr, seq) == ["생명력 28%", "생명력 25%"]


def test_edge_levels_and_shield_only():
    tr = BarTracker({"hp": BarCfg(enabled=True, pct=30), "mp": BarCfg(enabled=True, pct=25, shield_only=True)})
    for i in range(8):
        tr.update({"hp": 0.12, "mp": 0.20}, now=i * 0.25)
    assert tr.edge_levels(shield_on=True) == {"hp": 2, "mp": 1}      # 12% ≤ 30/2 → 위험
    assert tr.edge_levels(shield_on=False) == {"hp": 2}              # 마나실드 꺼짐 → 마나 화면 효과 없음
    assert tr.edge_levels(shield_on=None) == {"hp": 2, "mp": 1}      # 마나실드 감시 안 함 → 설정대로
    assert sorted(tr.text_rows()) == [("hp", 12), ("mp", 20)]


def test_disabled_resource_silent():
    tr = BarTracker({"sp": BarCfg(enabled=False, pct=20)})
    assert run(tr, [10] * 8, key="sp") == [] and tr.edge_levels() == {}


SOFT = {   # UI 배율 조정 켬 · 100% · 마비옛체 — 스태미나 테두리가 안쪽 색과 섞여 그려짐 (화면 숫자)
    "soft100_qhd.png": (4576 / 5362, 5201 / 5889, 4258 / 5028),
    "soft100_4k.png": (1706 / 6869, 3837 / 5288, 3444 / 4849),       # 생명력 경계가 숫자 밑
}


@pytest.mark.parametrize("name", sorted(SOFT))
def test_soft_ui_100(name):
    from core import screen
    screen.set_screen("100_mabi")
    try:
        r = read_bars(cv2.imread(str(FIX / name)))
    finally:
        screen.set_screen("100")
    for k, want in zip(("hp", "mp", "sp"), SOFT[name]):
        assert r[k] is not None and abs(r[k] - want) < 0.015, (k, r[k], want)
