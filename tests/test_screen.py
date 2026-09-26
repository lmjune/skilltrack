"""UI 크기 변형 (core/screen.py).

- 100% 는 모든 치수가 기존 상수와 정확히 같아야 한다 (기존 동작 보존).
- 150% 픽스처: tests/fixtures/variants/150_mabi|150_nanum/ 아래 상태창 연속 저장 (win/snap.py F9, 1초 간격).
  시간이 1초씩 줄어드므로 정답 없이도 '전부 읽히고, 행마다 값이 1초씩 줄어드는지'로 검증한다.
"""
from pathlib import Path

import cv2
import pytest

from core import screen
from core.digits import GlyphLib, read_time
from core.rows import detect_rows
from core.status import parse_rows

FIX = Path(__file__).parent / "fixtures" / "variants"


@pytest.fixture(autouse=True)
def reset_screen():
    yield
    screen.set_screen("100")


def test_100_keeps_constants():
    screen.set_screen("100")
    assert [screen.px(v) for v in (8, 10, 12, 20, 24, 30, 80)] == [8, 10, 12, 20, 24, 30, 80]
    assert screen.area(80) == 80
    assert screen.pitch_matches(24) and not screen.pitch_matches(36)
    assert not screen.current().fuzzy


def test_150_scales():
    screen.set_screen("150_mabi")
    assert screen.px(24) == 36 and screen.area(80) == 180
    assert screen.pitch_matches(36) and not screen.pitch_matches(24)
    assert screen.current().fuzzy and screen.current().glyphs.exists()


def test_unknown_key_falls_back():
    assert screen.set_screen("nope").key == "100"


def _frames(key):
    return sorted(p for p in (FIX / key).rglob("*.png") if not p.name.startswith("_"))


@pytest.mark.parametrize("key", ["150_mabi", "150_nanum"])
def test_150_status_countdown(key):
    frames = _frames(key)
    if len(frames) < 5:
        pytest.skip(f"픽스처 없음: {FIX / key}")
    sc = screen.set_screen(key)
    lib = GlyphLib.load(sc.glyphs, fuzzy=True)
    L = detect_rows(cv2.imread(str(frames[0])))
    assert L is not None and screen.pitch_matches(L.pitch)
    assert len(L.sections[0]) >= 5

    seqs, unread = {}, []
    for i, f in enumerate(frames):
        for st in parse_rows(cv2.imread(str(f)), L):
            if st.time_img is None:
                continue
            r = read_time(st.time_img, lib)
            if r.seconds is None:
                unread.append((f.name, st.index, r.text))
            seqs.setdefault(st.index, []).append((i, r.seconds))
    assert not unread, unread[:5]
    for row, seq in seqs.items():
        for (i0, a), (i1, b) in zip(seq, seq[1:]):
            if a is None or b is None or i1 != i0 + 1:
                continue
            assert a - b in (0, 1, 2), f"행{row}: 프레임 {i0}→{i1} 값 {a}→{b}"


# 실사용 진단 프레임 (나눔고딕 150%, 진단 자동 저장). 파일 → {행: 시간 글자}. 없으면 건너뜀
DIAG_150_NANUM = {
    "20260926_093815_unknown_row1.png": {0: "17초", 1: "2분27초", 9: "2분19초"},
    "20260926_093825_unknown_row1.png": {0: "7초", 1: "2분17초", 9: "26초"},
    "20260926_093903_unknown_row0.png": {0: "2분29초", 1: "1분40초", 9: "1분31초"},
    "20260926_093929_timelost_row0.png": {0: "59초", 1: "1분14초", 9: "1분5초"},      # 녹색 이펙트 앞 빨간 글자
    "20260926_094457_unknownstate_row2.png": {0: "13초", 2: "2분37초"},
    "20260926_094613_unknownstate_row3.png": {2: "1분22초"},
}


@pytest.mark.parametrize("name,expect", DIAG_150_NANUM.items())
def test_150_nanum_diag(name, expect):
    p = FIX / "diag_150_nanum" / name
    if not p.exists():
        pytest.skip(f"픽스처 없음: {p}")
    sc = screen.set_screen("150_nanum")
    lib = GlyphLib.load(sc.glyphs, fuzzy=True)
    img = cv2.imread(str(p))
    L = detect_rows(img)
    got = {s.index: read_time(s.time_img, lib).text for s in parse_rows(img, L) if s.time_img is not None}
    for row, text in expect.items():
        assert got.get(row) == text, (row, got.get(row), text)


def test_150_suffix_keeps_name():
    """분홍 접미어 '(투안의 노래)' 가 붙어도 이름이 사라지지 않고 넓어진다 (전엔 시간이 이름으로 잡혀 'N초' 접미어가 쌓였다)."""
    a = FIX / "diag_150_nanum" / "20260926_093815_unknown_row1.png"      # 비바체
    b = FIX / "diag_150_nanum" / "20260926_093903_unknown_row0.png"      # 비바체(투안의 노래)
    if not (a.exists() and b.exists()):
        pytest.skip("픽스처 없음")
    screen.set_screen("150_nanum")
    wa = [s for s in parse_rows(cv2.imread(str(a)), detect_rows(cv2.imread(str(a)))) if s.index == 0][0]
    wb = [s for s in parse_rows(cv2.imread(str(b)), detect_rows(cv2.imread(str(b)))) if s.index == 0][0]
    assert wa.name_width and wb.name_width and wb.name_width > wa.name_width + 30
    assert wb.time_range is not None and wb.name_range[1] < wb.time_range[0]


# 밝은 돌바닥 (나눔고딕 150%). 글자 가장자리가 255 로 포화돼 획이 굵어진다 → 골격 비교로 읽는다.
# 안전 조건: 틀리게 읽은 것은 0 (못 읽는 건 허용 — 추정 타이머와 자동 학습이 메운다), 절반 이상은 읽을 것.
BRIGHT_150_NANUM = {
    "20260926_095605_unknown_row2.png": {0: "4분41초", 2: "3분0초", 6: "3분0초", 9: "2분59초", 10: "2분59초", 11: "3분0초"},
    "20260926_095615_unknown_row6.png": {0: "4분31초", 1: "2분52초", 2: "2분50초", 6: "2분50초", 9: "2분49초", 10: "2분50초", 11: "2분50초"},
    "20260926_095626_unknown_row2.png": {0: "4분21초", 1: "2분56초", 2: "2분40초", 6: "2분40초", 9: "2분39초", 10: "2분40초", 11: "2분40초"},
    "20260926_095636_unknown_row1.png": {0: "4분11초", 1: "2분46초", 2: "2분30초", 6: "2분30초", 9: "2분29초", 10: "2분30초", 11: "2분30초"},
    "20260926_095646_unknown_row1.png": {0: "4분1초", 1: "2분36초", 2: "2분20초", 6: "2분20초", 9: "2분19초", 10: "2분20초", 11: "2분20초"},
    "20260926_095656_unknown_row1.png": {0: "3분51초", 1: "2분26초", 2: "2분10초", 6: "2분10초", 9: "2분8초", 10: "2분10초", 11: "2분10초"},
    "20260926_095706_unknown_row2.png": {0: "3분41초", 1: "2분16초", 2: "2분0초", 6: "2분0초", 9: "1분58초", 10: "2분0초", 11: "2분0초"},
    "20260926_095716_unknown_row0.png": {0: "3분30초", 1: "2분5초", 2: "1분49초", 6: "1분49초", 9: "1분48초", 10: "1분49초", 11: "1분49초"},
}
BRIGHT_LAYOUT = "diag_150_nanum/20260926_094421_unknownstate_row2.png"   # 같은 영역, 어두운 곳에서 잡은 레이아웃


def test_150_nanum_bright_never_wrong():
    lay = FIX / BRIGHT_LAYOUT
    if not lay.exists() or not (FIX / "bright_150_nanum").exists():
        pytest.skip("픽스처 없음")
    sc = screen.set_screen("150_nanum")
    lib = GlyphLib.load(sc.glyphs, fuzzy=True)
    L = detect_rows(cv2.imread(str(lay)))
    wrong, read, total = [], 0, 0
    for name, expect in BRIGHT_150_NANUM.items():
        img = cv2.imread(str(FIX / "bright_150_nanum" / name))
        got = {s.index: read_time(s.time_img, lib) for s in parse_rows(img, L) if s.time_img is not None}
        for row, text in expect.items():
            total += 1
            r = got.get(row)
            if r is None or r.seconds is None:
                continue
            read += 1
            if r.text != text:
                wrong.append((name, row, r.text, text))
    assert not wrong, wrong


def _sec(t):
    m, s = t.split("분") if "분" in t else ("0", t)
    return int(m) * 60 + int(s.rstrip("초"))


def test_150_nanum_bright_learns():
    """실행 중처럼: 못 읽은 글자를 (추정값 ±1초 + 골격 후보)로 배우면 대부분 읽히고, 여전히 틀린 건 0."""
    import types
    from win.session import Session
    lay = FIX / BRIGHT_LAYOUT
    if not lay.exists() or not (FIX / "bright_150_nanum").exists():
        pytest.skip("픽스처 없음")
    sc = screen.set_screen("150_nanum")
    lib = GlyphLib.load(sc.glyphs, fuzzy=True)
    L = detect_rows(cv2.imread(str(lay)))
    fake = types.SimpleNamespace(lib=lib)
    for jitter in (1, -1):
        for name, expect in BRIGHT_150_NANUM.items():
            for s in parse_rows(cv2.imread(str(FIX / "bright_150_nanum" / name)), L):
                if s.index not in expect or s.time_img is None:
                    continue
                rr = read_time(s.time_img, lib)
                if rr.unknown:
                    got = Session._resolve_by_skeleton(fake, rr, _sec(expect[s.index]) + jitter)
                    for label, g in got or []:
                        lib.learn(label, g.mask)
    wrong, read, total = [], 0, 0
    for name, expect in BRIGHT_150_NANUM.items():
        got = {s.index: read_time(s.time_img, lib)
               for s in parse_rows(cv2.imread(str(FIX / "bright_150_nanum" / name)), L) if s.time_img is not None}
        for row, text in expect.items():
            total += 1
            r = got.get(row)
            if r is not None and r.seconds is not None:
                read += 1
                if r.text != text:
                    wrong.append((name, row, r.text, text))
    assert not wrong, wrong
    assert read >= total * 0.75, (read, total)


# ---------------------------------------------------------------- 바깥 배경 (연속 저장, 1초 간격)
# tests/fixtures/variants/outdoor/<이름>/*.png|webp. 레이아웃은 같은 글꼴의 어두운 연속 저장 첫 장에서 잡고
# 영역 차이(dx)만큼 옮긴다 (밝은 곳에선 행 검출을 안 한다 — 실사용도 어두운 곳에서 잡은 저장본을 쓴다).
OUTDOOR = {   # 이름: (글꼴, dx, 학습 후 최소 읽기 비율)
    "bluestone_nanum": ("150_nanum", 0, 0.7),
    "grass_nanum": ("150_nanum", 30, 0.85),
    "stone_mabi": ("150_mabi", 30, 0.7),
    "grass_mabi": ("150_mabi", 30, 0.9),
}


def _outdoor_frames(name):
    d = FIX / "outdoor" / name
    return sorted([*d.rglob("2*.png"), *d.rglob("2*.webp")]) if d.exists() else []


def _outdoor_layout(font, dx):
    import copy
    from core.rows import Row
    base = _frames(font)
    if not base:
        return None
    L = copy.deepcopy(detect_rows(cv2.imread(str(base[0]))))
    L.rows = [Row(y=r.y, icon=(r.icon[0] - dx, *r.icon[1:]), text=(r.text[0] - dx, *r.text[1:])) for r in L.rows]
    return L


def _stamp(p):
    import re
    from datetime import datetime
    m = re.search(r"(\d{8}_\d{6}_\d{3})", p.name)
    return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S_%f").timestamp()


@pytest.mark.parametrize("name", list(OUTDOOR))
def test_outdoor_reads_after_learning(name):
    """실행 중처럼 읽으면서 배운 뒤: 행마다 1초에 0~2초씩 줄거나 갱신(크게 증가)만 있어야 한다 (틀린 글자 = 튀는 값)."""
    import types
    from win.session import Session
    font, dx, min_ratio = OUTDOOR[name]
    frames = _outdoor_frames(name)
    sc = screen.set_screen(font)
    L = _outdoor_layout(font, dx)
    if len(frames) < 10 or L is None:
        pytest.skip("픽스처 없음")
    lib = GlyphLib.load(sc.glyphs, fuzzy=True)
    fake = types.SimpleNamespace(lib=lib, last_val={})
    fake._resolve_by_skeleton = types.MethodType(Session._resolve_by_skeleton, fake)
    orig = screen.user_glyphs
    screen.user_glyphs = lambda: None                 # 테스트는 파일에 쓰지 않음
    try:
        for f in frames:
            t = _stamp(f)
            for s in parse_rows(cv2.imread(str(f)), L):
                if s.time_img is None:
                    continue
                rr = read_time(s.time_img, lib)
                if rr.seconds is not None:
                    fake.last_val[s.index] = (rr.seconds, t)
                elif rr.unknown and rr.plausible:
                    Session._learn_unknown(fake, s.index, rr, t)
    finally:
        screen.user_glyphs = orig
    seqs, total, read = {}, 0, 0
    for f in frames:
        t = _stamp(f)
        for s in parse_rows(cv2.imread(str(f)), L):
            if s.time_img is None:
                continue
            rr = read_time(s.time_img, lib)
            if not rr.plausible:
                continue
            total += 1
            if rr.seconds is not None:
                read += 1
                seqs.setdefault(s.index, []).append((t, rr.seconds))
    odd = []
    for row, seq in seqs.items():
        for (t0, a), (t1, b) in zip(seq, seq[1:]):
            dt = t1 - t0
            if b > a + 5:
                continue                              # 갱신·다른 버프로 바뀜
            off = abs(b - (a - dt))
            if 1.6 < off <= 15:                       # 글자 하나 잘못 읽으면 1~9 (일의 자리)·10 안팎 차이. 더 크면 행 내용이 바뀐 것
                odd.append((row, a, b, round(dt, 1)))
    assert not odd, odd[:5]
    assert read >= total * min_ratio, (read, total)


@pytest.mark.parametrize("name", list(OUTDOOR))
def test_outdoor_pink_suffix_single_transition(name):
    """분홍 접미어 판정은 배경이 바뀌어도 깜빡이지 않는다: 연속 저장 동안 '없음 → 있음' 한 번만."""
    from core import variants
    font, dx, _ = OUTDOOR[name]
    frames = _outdoor_frames(name)
    screen.set_screen(font)
    L = _outdoor_layout(font, dx)
    if len(frames) < 10 or L is None:
        pytest.skip("픽스처 없음")
    seq = []
    for f in frames:
        s = [q for q in parse_rows(cv2.imread(str(f)), L) if q.index == 0][0]
        seq.append(bool(s.name_img is not None and variants.pink_suffix(s.name_img, 42)))
    flips = sum(a != b for a, b in zip(seq, seq[1:]))
    assert flips == 1 and seq[-1] is True, seq
