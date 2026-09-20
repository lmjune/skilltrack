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

from core.paths import PROFILES
VAR_DIR = PROFILES / "variants"
MATCH_THR = 0.97


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
            out.append({"key": j["key"], "mask": mask, "label": j.get("label", ""), "extends": bool(j.get("extends", False))})
        except Exception:
            pass
    return out


def save(pid, row, mask, thumb_bgr, label="", extends=False) -> str:
    d = _folder(pid, row); d.mkdir(parents=True, exist_ok=True)
    key = _key(mask)
    (d / f"{key}.json").write_text(json.dumps({
        "key": key, "label": label, "extends": extends,
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


def contains(suffix_mask, template) -> bool:
    """접미어 마스크 안에 템플릿이 (거의) 그대로 들어 있는가. 부분 매칭이라 겹친 접미어도 됨."""
    if suffix_mask.shape[0] < template.shape[0] or suffix_mask.shape[1] < template.shape[1]:
        return False
    a = suffix_mask.astype(np.float32); b = template.astype(np.float32)
    if b.sum() == 0:
        return False
    res = cv2.matchTemplate(a, b, cv2.TM_CCORR_NORMED)
    return float(res.max()) >= MATCH_THR


def classify(pid, row, suffix_mask, thumb_bgr, known=None):
    """접미어 마스크 → (extends: bool, key, is_new). 모르는 접미어는 저장하고 extends=False."""
    known = known if known is not None else load(pid, row)
    hit = [v for v in known if contains(suffix_mask, v["mask"])]
    if hit:
        return any(v["extends"] for v in hit), hit[0]["key"], False
    key = save(pid, row, suffix_mask, thumb_bgr)
    return False, key, True