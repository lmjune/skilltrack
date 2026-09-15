"""
게임 텍스트의 '획' 픽셀 추출. 배경 무관.

게임은 글자를 흰색(활성) / 회색 127(비활성) / 빨강(1분 미만 시간) 으로 그리고
항상 검은 외곽선을 두른다. 그래서 '해당 색이면서 근처에 어두운 픽셀이 있는 것'만 획으로 본다.
반투명 패널 뒤의 배경(눈밭, 나무, 이펙트)은 외곽선이 없어 제외된다.
"""
import cv2
import numpy as np


def stroke_masks(bgr):
    """(white, gray, red) 불리언 마스크."""
    b, g, r = [bgr[:, :, i].astype(np.int16) for i in range(3)]
    mx, mn = np.maximum(np.maximum(b, g), r), np.minimum(np.minimum(b, g), r)
    neutral = (mx - mn) <= 40
    dark = (mx <= 80)
    near_dark = cv2.dilate(dark.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    white = neutral & (mn >= 190) & near_dark
    gray = neutral & (mn >= 95) & (mx <= 145) & near_dark
    red = (r >= 180) & (g <= 100) & (b <= 100) & near_dark
    return white, gray, red


def any_stroke(bgr):
    w, g, r = stroke_masks(bgr)
    return w | g | r