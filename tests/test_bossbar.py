"""보스 체력바/디버프 띠 읽기 + 추적기. fixtures/boss/*.png (4K 원본에서 자른 850×250 영역)"""
from pathlib import Path
import cv2
import numpy as np
import pytest

from core.bossbar import find_bar, find_slots, read_bar, read_label, IconLib, INNER
from core.bosstrack import BossTracker, DebuffWatch
from core.digits import GlyphLib

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures" / "boss"
LIB = ROOT / "assets" / "glyphs.json"
STRIP, NOSTRIP = FIX / "bar_09_16_194911.png", FIX / "bar_09_20_121449.png"   # 페타크(띠 7칸) / 제바흐(띠 없음)
TRUTH = FIX / "truth.json"                                                        # 파일 → {labels, icons} (전 프레임 실측)
ICONS = ROOT / "assets" / "boss_icons"
pytestmark = pytest.mark.skipif(not (STRIP.exists() and NOSTRIP.exists() and LIB.exists()), reason="fixture 없음")

LABELS = ["4M", "4M", "9M", "4M", "", "9M", "4M"]


@pytest.fixture(scope="module")
def lib():
    return GlyphLib.load(LIB)


def test_anchor_and_slots():
    img = cv2.imread(str(STRIP))
    a = find_bar(img)
    assert a is not None and a.text_y == 130 and a.pct_x1 == 667
    slots = find_slots(img, a)
    assert [s.x for s in slots] == [166 + 18 * i for i in range(7)]


def test_labels(lib):
    r = read_bar(cv2.imread(str(STRIP)), lib)
    assert [s.label for s in r.slots] == LABELS
    assert [s.seconds for s in r.slots] == [240, 240, 540, 240, None, 540, 240]


def test_bar_without_strip(lib):
    r = read_bar(cv2.imread(str(NOSTRIP)), lib)
    assert r.present and not r.has_strip


def test_no_bar(lib):
    img = cv2.imread(str(STRIP))[:80]        # 띠 부분만 (바 없음)
    assert not read_bar(img, lib).present


@pytest.mark.skipif(not TRUTH.exists(), reason="truth.json 없음")
def test_all_frames_labels_and_icons(lib):
    """13프레임: 어두움·흰 얼음·인벤 창 겹침·색 다른 바(보라/녹/노랑+빨강)·만료 직전 깜빡임(≤5초, 25% 밝기)."""
    import json
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    icons = IconLib(ICONS)
    for name, t in truth.items():
        r = read_bar(cv2.imread(str(FIX / name)), lib, icons)
        assert r.present, name
        assert [s.label for s in r.slots] == t["labels"], name
        assert [s.icon_id for s in r.slots] == t["icons"], name
        assert all(s.icon_id or icons.is_dim(s.icon) for s in r.slots), name   # 어두운 깜빡임은 모르는 아이콘일 수 있음


def test_dim_variant_matches(lib):
    """만료 5초 전 어두운 아이콘이 1초 전 밝은 아이콘과 같은 id 로 잡힌다."""
    icons = IconLib(ICONS)
    a = read_bar(cv2.imread(str(FIX / "bar_09_20_114941.png")), lib, icons).slots[6]
    b = read_bar(cv2.imread(str(FIX / "bar_09_20_114945.png")), lib, icons).slots[6]
    assert (a.label, b.label) == ("5", "1") and icons.is_dim(a.icon) and not icons.is_dim(b.icon)
    assert a.icon_id == b.icon_id


def test_read_label_forms(lib):
    r = read_bar(cv2.imread(str(STRIP)), lib)
    assert read_label(r.slots[0].label_img, lib) == ("4M", 240)
    assert read_label(np.zeros((9, 15, 3), np.uint8), lib) == ("", None)


def test_icon_lib(tmp_path, lib):
    r = read_bar(cv2.imread(str(STRIP)), lib)
    icons = IconLib(tmp_path)
    keys = [icons.add(s.icon, name=f"d{i}") for i, s in enumerate(r.slots)]
    assert len(set(keys)) == 7
    r2 = read_bar(cv2.imread(str(STRIP)), lib, icons)
    assert [s.icon_id for s in r2.slots] == keys
    # 다른 곳에 저장한 라이브러리 다시 읽어도 같은 결과
    icons2 = IconLib(tmp_path)
    assert icons2.match(r.slots[3].icon)[0] == keys[3]
    assert icons2.match(np.full((INNER, INNER, 3), 128, np.uint8))[0] is None


def test_tracker_missing_and_burst(tmp_path, lib):
    img = cv2.imread(str(STRIP))
    icons = IconLib(tmp_path)
    r = read_bar(img, lib)
    k = [icons.add(s.icon) for s in r.slots]
    watches = [DebuffWatch(k[0], "물리약화"), DebuffWatch("absent0000", "마법약화"),
               DebuffWatch(k[2], "붕괴의 파동", burst=True)]
    tr = BossTracker(watches)
    full = read_bar(img, lib, icons)
    ev = []
    for i in range(4):                                   # 빠짐은 4프레임 연속이어야 확정
        ev += tr.update(full, now=100 + i)
    kinds = [(e.kind, e.label) for e in ev]
    assert ("start", "") in kinds and ("found", "물리약화") in kinds and ("missing", "마법약화") in kinds
    assert ("burst", "붕괴의 파동 적용!") in kinds
    assert [s.watch.label for s in tr.shown(101)] == ["마법약화"]
    # 바 잠깐 사라짐 → 유지, 오래 사라짐 → 종료
    empty = read_bar(img[:80], lib, icons)
    assert tr.update(empty, now=105) == [] and tr.active
    assert [e.kind for e in tr.update(empty, now=140)] == ["end"] and not tr.active


def test_strip_panel_without_icons(lib):
    """띠 패널이 있으면 아이콘 0개(아무것도 안 걸림)여도 감시 대상. 제바흐(패널 없음)는 아님."""
    r = read_bar(cv2.imread(str(STRIP)), lib)
    assert r.has_strip
    r2 = read_bar(cv2.imread(str(NOSTRIP)), lib)
    assert r2.present and not r2.has_strip
    # 띠 자리를 배경으로 덮어 아이콘을 없애도 패널 판정은 유지
    img = cv2.imread(str(STRIP)); a = r.anchor
    img[a.text_y - 46:a.text_y - 18, a.text_x - 8:a.text_x + 160] = 50
    r3 = read_bar(img, lib)
    assert r3.has_strip and not r3.slots


def test_live_bold_font(lib):
    """실제 화면(dxcam)은 바 글자가 굵다. 스크린샷 픽스처와 '%' 모양만 다르고 위치·띠·아이콘·라벨은 같다."""
    icons = IconLib(ICONS)
    r = read_bar(cv2.imread(str(FIX / "live_160142.png")), lib, icons)
    assert r.present and r.anchor.style == "bold" and r.anchor.pct_x1 == 667 and r.anchor.text_y == 130
    assert [s.x for s in r.slots] == [166, 184] and [s.label for s in r.slots] == ["4M", "4M"]
    assert all(s.icon_id for s in r.slots)          # 스크린샷에서 등록한 아이콘과 동일하게 매칭