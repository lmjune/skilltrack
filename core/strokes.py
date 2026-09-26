"""
게임 텍스트의 '획' 픽셀 추출. 배경 무관.

게임은 글자를 흰색(활성) / 회색 127(비활성) / 빨강(1분 미만 시간) 으로 그리고
항상 검은 외곽선을 두른다. 그래서 '해당 색의 작은 덩어리이면서 테두리가 거의 전부 어두운 외곽선'인 것만 획으로 본다.
밝은 돌바닥은 색은 비슷해도 덩어리가 커서 걸러진다.
반투명 패널 뒤의 배경(눈밭, 나무, 이펙트)은 외곽선이 없어 제외된다.
"""
import cv2
import numpy as np

from core import screen


WHITE_MIN = 250        # 활성 글자는 불투명 255. 비활성은 50% 투명이라 배경이 아무리 밝아도 ~245 이하
WHITE_MIN_AA = 255     # 안티앨리어싱 글꼴 (UI 150%): 완전히 덮인 픽셀만. 가장자리는 배경 밝기에 따라 250 을 넘나든다
MAX_BLOB = 80          # 글자 획 덩어리 최대 픽셀 수 (한글 한 획 덩어리는 이보다 작다). UI 크기 배율² 적용
RING_DARK = 0.8        # 덩어리 테두리 중 어두운 픽셀 비율 최소
DARK_LUM = 80          # 외곽선으로 볼 휘도 상한
DARK_LUM_AA = 110      # 안티앨리어싱 글꼴 (UI 150%): 글자와 외곽선 사이에 중간 밝기 픽셀이 끼어 테두리가 덜 어둡다.
                       # 실측 (주황 나무 바닥, 회색 글자 66덩어리): 80 이면 55~90% 만 어두움 → 글자 절반이 탈락, 110 이면 전부 85% 이상


def _small_blobs(cand):
    """cand 의 연결 덩어리 중 MAX_BLOB 이하인 것만 (글자 획 크기)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), connectivity=8)
    out = np.zeros_like(cand)
    limit = screen.area(MAX_BLOB)
    for i in range(1, n):
        if stats[i][4] <= limit:
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
    limit = screen.area(MAX_BLOB)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area > limit:
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
    dark = (lum <= (DARK_LUM_AA if screen.current().fuzzy else DARK_LUM))
    # 활성 글자·시간 글자는 정확히 255 (불투명). 패널 틴트 때문에 배경은 255가 못 되므로 색만으로 확정.
    # 외곽선은 배경에 따라 있기도 없기도 해서 조건에 넣지 않는다. 작은 덩어리 조건만.
    # UI 150%: 글자 가장자리가 배경과 섞여, 밝은 바닥에선 가장자리도 250 을 넘어 글자가 한 겹 두꺼워진다
    # (실측: 돌바닥 위 '0' 가장자리 241~253). 완전히 덮인 픽셀은 정확히 255 → 150% 는 255 만 흰 글자로
    white = _small_blobs(neutral & (mn >= (WHITE_MIN_AA if screen.current().fuzzy else WHITE_MIN)))
    if screen.current().fuzzy:
        # UI 150%: 빨간 글자에 배경이 살짝 섞여 (255,3,3)~(255,12,12) 가 나온다 (실측: 녹색 이펙트 앞 '59초' 의 60%).
        # G≈B (회색 섞임) 인 것만 허용 → 주황·분홍 이펙트(G≠B)는 여전히 제외
        # 실측 (돌바닥·풀밭·푸른 돌): 빨간 글자는 R 이 정확히 255, G·B 는 배경색이 비친 만큼 (0~50, 배경 색 비율 그대로).
        # → R≥250 이고 G·B 가 둘 다 낮은 것. 주황 배경(G≈150)·분홍 접미어(G≈190)는 G 가 커서 제외
        red = _small_blobs((r >= 250) & (np.maximum(g, b) <= 60))
    else:
        red = _small_blobs((r >= 190) & (g <= 2) & (b <= 2))  # 빨간 글자는 정확히 (255,0,0). 이펙트는 G,B≥4
    # 비활성 글자 = 50% 투명 흰색 → (255+배경)/2. 어두운 배경에서만 배경과 구분되며, 그때는 외곽선이 보인다.
    gray = _enclosed(neutral & (mn >= 95) & (mn < WHITE_MIN), dark)
    return white, gray, red


def pink_mask(bgr):
    """이름 접미어 "(투안의 노래)" 의 분홍 글자 (UI 150% 실측: (255,193,203), (245,162,168) 등).
    흰/회색 마스크에 안 들어가서, 접미어가 붙은 이름은 획 밀도가 모자라 이름 자체가 사라졌다."""
    b, g, r = [bgr[:, :, i].astype(np.int16) for i in range(3)]
    return _small_blobs((r >= 230) & (g >= 140) & (g <= 215) & (b >= 140) & (b <= 225)
                        & (np.abs(g - b) <= 15) & (r - g >= 35))


def name_strokes(bgr):
    """이름 글자 획 (흰 + 회색, UI 150% 에선 분홍 접미어도)."""
    w, g, _ = stroke_masks(bgr)
    m = w | g
    if screen.current().fuzzy:
        m |= pink_mask(bgr)
    return m


def any_stroke(bgr):
    w, g, r = stroke_masks(bgr)
    return w | g | r