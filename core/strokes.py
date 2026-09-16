"""
게임 텍스트의 '획' 픽셀 추출. 배경 무관.

게임은 글자를 흰색(활성) / 회색 127(비활성) / 빨강(1분 미만 시간) 으로 그리고
항상 검은 외곽선을 두른다. 그래서 '해당 색의 작은 덩어리이면서 테두리가 거의 전부 어두운 외곽선'인 것만 획으로 본다.
밝은 돌바닥은 색은 비슷해도 덩어리가 커서 걸러진다.
반투명 패널 뒤의 배경(눈밭, 나무, 이펙트)은 외곽선이 없어 제외된다.
"""
import cv2
import numpy as np


WHITE_MIN = 250        # 활성 글자는 불투명 255. 비활성은 50% 투명이라 배경이 아무리 밝아도 ~245 이하
MAX_BLOB = 80          # 글자 획 덩어리 최대 픽셀 수 (한글 한 획 덩어리는 이보다 작다)
RING_DARK = 0.8        # 덩어리 테두리 중 어두운 픽셀 비율 최소


def _small_blobs(cand):
    """cand 의 연결 덩어리 중 MAX_BLOB 이하인 것만 (글자 획 크기)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), connectivity=8)
    out = np.zeros_like(cand)
    for i in range(1, n):
        if stats[i][4] <= MAX_BLOB:
            out |= labels == i
    return out


def _enclosed(cand, dark):
    """cand 의 연결 덩어리 중 '작고, 테두리가 거의 전부 어두운' 것만 남긴다.
    글자 획은 작은 덩어리를 검은 외곽선이 완전히 감싸고, 밝은 돌 타일은 줄눈에 싸여 있어도 덩어리가 크다."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), connectivity=8)
    out = np.zeros_like(cand)
    if n <= 1:
        return out
    dark_u8 = dark.astype(np.uint8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area > MAX_BLOB:
            continue
        y0, y1, x0, x1 = max(0, y - 1), y + h + 1, max(0, x - 1), x + w + 1
        comp = (labels[y0:y1, x0:x1] == i).astype(np.uint8)
        ring = cv2.dilate(comp, np.ones((3, 3), np.uint8)) - comp
        if ring.sum() == 0:
            continue
        if (ring & dark_u8[y0:y1, x0:x1]).sum() / ring.sum() >= RING_DARK:
            out[y0:y1, x0:x1] |= comp.astype(bool)
    return out


def stroke_masks(bgr):
    """(white, gray, red) 불리언 마스크."""
    b, g, r = [bgr[:, :, i].astype(np.int16) for i in range(3)]
    mx, mn = np.maximum(np.maximum(b, g), r), np.minimum(np.minimum(b, g), r)
    neutral = (mx - mn) <= 40
    lum = (0.114 * b + 0.587 * g + 0.299 * r)          # 휘도. 어두운 빨강(4,3,143)도 어둡다
    dark = (lum <= 80)
    # 활성 글자·시간 글자는 정확히 255 (불투명). 패널 틴트 때문에 배경은 255가 못 되므로 색만으로 확정.
    # 외곽선은 배경에 따라 있기도 없기도 해서 조건에 넣지 않는다. 작은 덩어리 조건만.
    white = _small_blobs(neutral & (mn >= WHITE_MIN))
    red = _small_blobs((r >= 190) & (g <= 2) & (b <= 2))      # 빨간 글자는 정확히 (255,0,0). 이펙트는 G,B≥4
    # 비활성 글자 = 50% 투명 흰색 → (255+배경)/2. 어두운 배경에서만 배경과 구분되며, 그때는 외곽선이 보인다.
    gray = _enclosed(neutral & (mn >= 95) & (mn < WHITE_MIN), dark)
    return white, gray, red


def any_stroke(bgr):
    w, g, r = stroke_masks(bgr)
    return w | g | r