"""
이름 접미어 변형: "전장의 서곡(투안의 노래)", "행진곡(하모니)(투안의 노래)" 처럼 이름 뒤에 붙는 글자.

접미어도 고정 폰트라 픽셀이 같다 → 획 마스크를 템플릿으로 저장하고 매칭한다.
처음 보는 접미어는 자동 저장(썸네일 포함). 유저가 감시 항목에서 "연장으로 취급" 을 체크하면
그 템플릿이 접미어 안에 포함될 때 연장 상태로 본다. (겹친 접미어도 부분 매칭으로 잡힘)

저장: profiles/variants/<pid>/<key>.json (+ .png 썸네일)  — 접미어는 어느 버프에 붙든 같은 글자라 프로필 단위로 공유
"""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from core import screen
from core.paths import PROFILES
VAR_DIR = PROFILES / "variants"
MATCH_THR = 0.97
MATCH_THR_AA = 0.88     # 안티앨리어싱 글꼴 (UI 150%): 같은 접미어도 찍히는 위치마다 가장자리가 달라 0.97 이면 매번 '새 접미어'


def _folder(pid, row=None):
    return VAR_DIR / f"{pid}"


def _key(mask):
    return hashlib.md5(mask.tobytes() + bytes(mask.shape)).hexdigest()[:10]


def load(pid, row) -> list[dict]:
    """[{key, mask, label, extends}]"""
    out = []
    d = _folder(pid, row)
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            mask = np.array([[c == "1" for c in r] for r in j["rows"]], dtype=bool)
            out.append({"key": j["key"], "mask": mask, "label": j.get("label", ""), "extends": bool(j.get("extends", False)),
                        "seen_rows": j.get("seen_rows")})  # 이 접미어가 붙어 본 행들 (감시 항목 화면에서 그 행에만 표시). 옛 파일은 None
                                                           # ("rows" 는 마스크 비트맵 키라 쓰면 안 됨)
        except Exception:
            pass
    return out


PINK_KEY = "pink"        # UI 150%: 분홍 접미어는 모양 대신 '분홍 글자가 있나'로 판정 → 하나의 항목
PINK_MIN = 20            # 분홍 글자 픽셀 최소 (100% 기준 넓이, 배율² 적용). 실측: 있으면 170~220, 없으면 0


def pink_suffix(name_img, base_w) -> bool:
    """기본 이름 뒤에 분홍 글자(투안의 노래 등)가 있는가. 모양 비교 없이 색만 → 배경이 바뀌어도 흔들리지 않는다
    (실측: 어두운 곳·푸른 돌·밝은 돌·풀밭 4곳, 두 글꼴 모두 있음 170~220px / 없음 0px)."""
    from core.strokes import pink_mask
    if name_img is None or name_img.shape[1] <= base_w:
        return False
    return int(pink_mask(name_img[:, base_w:]).sum()) >= screen.area(PINK_MIN)


def save(pid, row, mask, thumb_bgr, label="", extends=False, key=None) -> str:
    d = _folder(pid, row); d.mkdir(parents=True, exist_ok=True)
    key = key or _key(mask)
    (d / f"{key}.json").write_text(json.dumps({
        "key": key, "label": label, "extends": extends, "seen_rows": [int(row)] if row is not None else [],
        "rows": ["".join("1" if v else "0" for v in r) for r in mask]}, ensure_ascii=False), encoding="utf-8")
    if thumb_bgr is not None and thumb_bgr.size:
        cv2.imwrite(str(d / f"{key}.png"), thumb_bgr)
    return key


def set_flags(pid, row, key, label=None, extends=None):
    p = _folder(pid, row) / f"{key}.json"
    if not p.exists():
        return
    j = json.loads(p.read_text(encoding="utf-8"))
    if label is not None:
        j["label"] = label
    if extends is not None:
        j["extends"] = bool(extends)
    p.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")


def add_row(pid, key, row):
    """이 접미어가 row 에도 붙었다고 기록 (처음 한 번만 파일을 고친다)."""
    p = _folder(pid) / f"{key}.json"
    if not p.exists() or row is None:
        return
    j = json.loads(p.read_text(encoding="utf-8"))
    seen = [int(r) for r in (j.get("seen_rows") or [])]
    if int(row) not in seen:
        j["seen_rows"] = sorted(seen + [int(row)])
        p.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")


def contains(suffix_mask, template) -> bool:
    """접미어 마스크 안에 템플릿이 (거의) 그대로 들어 있는가. 부분 매칭이라 겹친 접미어도 됨."""
    if suffix_mask.shape[0] < template.shape[0] or suffix_mask.shape[1] < template.shape[1]:
        return False
    a = suffix_mask.astype(np.float32); b = template.astype(np.float32)
    if b.sum() == 0:
        return False
    res = cv2.matchTemplate(a, b, cv2.TM_CCORR_NORMED)
    return float(res.max()) >= (MATCH_THR_AA if screen.current().fuzzy else MATCH_THR)


def same_shape(a, b) -> bool:
    """두 접미어 마스크가 같은 글자인가 (겹치는 크기로 잘라 비교)."""
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    if h < 3 or w < 3 or abs(a.shape[1] - b.shape[1]) > 6:
        return False
    return contains(a, b[:h, :max(1, w - 2)])


def classify(pid, row, suffix_mask, thumb_bgr, known=None, save_new=True):
    """접미어 마스크 → (extends: bool, key, is_new). 모르는 접미어는 save_new 일 때만 저장, extends=False."""
    known = known if known is not None else load(pid, row)
    hit = [v for v in known if contains(suffix_mask, v["mask"])]
    if hit:
        return any(v["extends"] for v in hit), hit[0]["key"], False
    if not save_new:
        return False, None, False
    key = save(pid, row, suffix_mask, thumb_bgr)
    return False, key, True