"""투아림 읽기 (실제 화면 샘플: 4K·QHD UI 100%, 4K UI 150% 마비옛체·나눔고딕) + 알림 규칙."""
import json
from pathlib import Path

import cv2
import pytest

from core.tuarim import TuarimRead, TuarimReader, TuarimTracker, event_text

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures" / "tuarim"
ASSETS = ROOT / "assets" / "tuarim"


@pytest.mark.skipif(not (FIX / "truth.json").exists(), reason="fixture 없음")
def test_reads_all_samples_exactly():
    truth = json.loads((FIX / "truth.json").read_text(encoding="utf-8"))
    readers, wrong = {}, []
    for name, t in truth.items():
        key = (t["variant"], t["scale"])
        if key not in readers:
            readers[key] = TuarimReader(ASSETS / f"{t['variant']}.json", t["scale"])
        r = readers[key].read(cv2.imread(str(FIX / name)))
        if (r.dorca, r.pct) != (t["dorca"], t["pct"]):
            wrong.append((name, (t["dorca"], t["pct"]), (r.dorca, r.pct)))
    assert not wrong, wrong[:5]


def test_not_found_without_pink_box():
    import numpy as np
    r = TuarimReader(ASSETS / "100.json", 1.0).read(np.zeros((80, 90, 3), np.uint8))
    assert not r.found and r.dorca is None and r.pct is None


def feed(tr, seq):
    out = []
    for d, p in seq:
        for _ in range(2):                                   # 같은 값 2프레임 = 안정
            out += [event_text(e) for e in tr.update(TuarimRead(True, d, p))]
    return out


def test_soon_once_per_cycle_and_burst():
    tr = TuarimTracker(soon_pct=95)
    seq = [(15, p) for p in range(90, 100)] + [(15, 0), (15, 1)] + [(15, p) for p in range(93, 97)]
    assert feed(tr, seq) == ["곧 투아림 (약 30초)", "투아림!", "곧 투아림 (약 30초)"]


def test_unstable_value_ignored():
    tr = TuarimTracker(soon_pct=95)
    out = [event_text(e) for e in tr.update(TuarimRead(True, 15, 96))]    # 한 프레임만 → 무시
    out += [event_text(e) for e in tr.update(TuarimRead(True, 15, 50))]
    assert out == []


def test_dorca_low_once_until_recovered():
    tr = TuarimTracker(soon_pct=0, dorca_low=3)
    seq = [(15, 10), (5, 10), (3, 10), (2, 10), (1, 10), (8, 10), (2, 10)]
    assert feed(tr, seq) == ["도르카 부족 (3)", "도르카 부족 (2)"]


def test_dorca_low_not_said_at_start():
    """켤 때 이미 낮으면 말하지 않음 (상태창 '시작할 때 꺼져 있던 버프'와 같은 규칙). 회복 후 다시 떨어지면 말함."""
    tr = TuarimTracker(soon_pct=0, dorca_low=3)
    assert feed(tr, [(0, 10), (1, 10), (9, 10), (2, 10)]) == ["도르카 부족 (2)"]


def test_long_eta_in_minutes():
    from core.tuarim import TuarimEvent, speech_text
    assert event_text(TuarimEvent("soon", 570)) == "곧 투아림 (약 9분 30초)"
    assert speech_text(TuarimEvent("soon", 30)) == "투아림 30초 전"


def test_eta():
    tr = TuarimTracker()
    feed(tr, [(15, 90)])
    assert tr.eta() == 60


@pytest.mark.skipif(not (FIX / "truth.json").exists(), reason="fixture 없음")
def test_tight_region_cutting_100_is_unknown_not_zero():
    """드래그 영역이 좁아 '100%' 의 '1' 이 잘리면 0% 로 읽지 말고 모름 (예전: 나눔고딕에서 100% → 0%)."""
    truth = json.loads((FIX / "truth.json").read_text(encoding="utf-8"))
    name = next(k for k, t in truth.items() if k.startswith("nanum100/") and t["pct"] == 100)
    img = cv2.imread(str(FIX / name))
    R = TuarimReader(ASSETS / "150_nanum.json", 1.5)
    assert R.read(img).pct == 100
    from core.tuarim import find_pink
    px = find_pink(img, 1.5)[0]
    cut = img[:, px - 6:]                      # 분홍 칸 바로 왼쪽까지만 드래그 → '1' 이 잘림
    assert R.read(cut).pct is None
