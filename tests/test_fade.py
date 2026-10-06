"""화면 전환 페이드에서 거짓 '꺼짐'이 나지 않는지 (core/pixelwatch.steady_off + 추적기)."""
from types import SimpleNamespace as NS

import numpy as np

from core.pixelwatch import NameSite, read_site, steady_off
from core.tracker import Tracker, Watch

MASK = np.zeros((7, 20), bool)
MASK[1:6, 2:18:2] = True                      # 이름 획 자리 (대충)
SITE = NameSite(0, 0, MASK)


def frame(glyph, bg=40):
    f = np.full((7, 20, 3), bg, np.uint8)
    f[MASK] = glyph
    return f


def run(levels):
    """프레임마다 글자 밝기 → 추적기 이벤트 (5fps, 디바운스 3, 실제 세션과 같은 판정)."""
    t = Tracker([Watch(b"a", "마나실드", row_index=0, alert_off=True)], debounce=3)
    prev, events = None, []
    for i, lv in enumerate(levels):
        rd = read_site(frame(lv), SITE)
        active = {"on": True, "off": False}.get(rd.state)
        if rd.state == "off" and not steady_off(rd, prev):
            active = None
        prev = rd.level
        events += [e.kind for e in t.update([NS(index=0, active=active, name_width=None, extended=None)], {}, now=i * 0.2)]
    return events


def test_fade_to_black_is_not_off():
    # 켜진 버프(255) → 1초 동안 어두워짐 (화면 전환) → 검은 화면 → 다시 밝아짐
    fade = [255] * 5 + [235, 215, 195, 175, 155, 135, 115, 95, 60, 20] + [5] * 5 + [60, 120, 180, 230] + [255] * 5
    assert "off" not in run(fade)


def test_slow_fade_is_not_off():
    fade = [255] * 5 + list(range(250, 90, -8)) + [255] * 5      # 프레임당 8씩 (2초 넘게 걸리는 페이드)
    assert "off" not in run(fade)


def test_real_off_still_detected():
    assert run([255] * 5 + [209] * 6) == ["off"]                 # 진짜 꺼짐: 209 고정
    assert run([255] * 5 + [127] * 6) == ["off"]                 # 던전 등 127


def frame_outlined(glyph, bg):
    """흰 글자 + 1px 어두운 테두리 (실제 상태창 글자처럼), 바깥은 bg."""
    import cv2
    f = np.full((7, 20, 3), bg, np.uint8)
    ring = cv2.dilate(MASK.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~MASK
    f[ring] = 20
    f[MASK] = glyph
    return f


def run_frames(frames):
    t = Tracker([Watch(b"a", "반신화", row_index=0, alert_off=True)], debounce=3)
    prev, events = None, []
    for i, f in enumerate(frames):
        rd = read_site(f, SITE)
        active = {"on": True, "off": False}.get(rd.state)
        if rd.state == "off" and not steady_off(rd, prev):
            active = None
        prev = rd.level
        events += [e.kind for e in t.update([NS(index=0, active=active, name_width=None, extended=None)], {}, now=i * 0.2)]
    return events


def test_white_flash_on_off_buff_is_not_on_then_off():
    """꺼진 버프(회색)가 화면이 하얗게 될 때 '켜짐'으로 바뀌었다가 돌아오며 '꺼짐' 알림 → 안 나야 함."""
    off = frame_outlined(209, 60)
    white = np.full((7, 20, 3), 255, np.uint8)                   # 화면 전체 흰색 1.5초
    assert run_frames([off] * 5 + [white] * 8 + [off] * 6) == []


def test_real_white_text_on_bright_background_still_on():
    """밝은 배경(눈밭 등)이어도 테두리가 있는 진짜 흰 글자는 켜짐."""
    rd = read_site(frame_outlined(255, 255), SITE)
    assert rd.state == "on"