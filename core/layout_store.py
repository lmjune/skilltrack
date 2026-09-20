"""
상태창 레이아웃 저장/복원. 프로필(캐릭터) id 별로 profiles/layouts/<pid>.json.
행 좌표 + 이름 지문 + 획 자리(활성/비활성 판정용) + 시간 끝 열.
"""
import base64
import json
from pathlib import Path

from core.rows import Row, RowLayout
from core.pixelwatch import NameSite, make_site, read_site

from core.paths import PROFILES
LAYOUT_DIR = PROFILES / "layouts"


def path(pid):
    return LAYOUT_DIR / f"{pid}.json"


def save(pid, layout: RowLayout, states, rect, frame):
    pinned = set(layout.sections[0]) if layout.sections else set()
    by = {s.index: s for s in states}
    rows = []
    for i in sorted(pinned):
        if i not in by:
            continue
        s = by[i]
        d = {"index": i, "icon": list(layout.rows[i].icon), "text": list(layout.rows[i].text),
             "name_fp": base64.b64encode(s.name_fp).decode()}
        if s.name_range is not None:
            d["site"] = make_site(frame, layout.rows[i].text, s.name_range).to_json()
        rows.append(d)
    data = {"rect": list(rect), "pitch": layout.pitch, "right": layout.right, "time_right": layout.time_right, "rows": rows}
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    path(pid).write_text(json.dumps(data, indent=1), encoding="utf-8")


def load(pid):
    """(rect, layout, {row: name_fp}, {row: NameSite}) 또는 None"""
    p = path(pid)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    if not d.get("rows"):
        return None
    rows = [Row(y=r["icon"][1], icon=tuple(r["icon"]), text=tuple(r["text"])) for r in d["rows"]]
    layout = RowLayout(pitch=d["pitch"], icon_x=rows[0].icon[0], icon_w=rows[0].icon[2], icon_h=rows[0].icon[3],
                       text_x=rows[0].text[0], right=d.get("right", rows[0].text[0] + rows[0].text[2]),
                       rows=rows, sections=[list(range(len(rows)))], time_right=d.get("time_right"))
    fps = {i: base64.b64decode(r["name_fp"]) for i, r in enumerate(d["rows"])}
    sites = {i: NameSite.from_json(r["site"]) for i, r in enumerate(d["rows"]) if "site" in r}
    return tuple(d["rect"]), layout, fps, sites


def delete(pid):
    p = path(pid)
    if p.exists():
        p.unlink()


def verify(frame, sites: dict) -> float:
    """저장된 획 자리에서 활성/비활성이 확정적으로 읽히는 행의 비율. 배경 무관."""
    if not sites:
        return 0.0
    reads = [read_site(frame, s) for s in sites.values()]
    return sum(1 for r in reads if r.state != "unknown") / len(reads)


def update_time_right(pid, time_right):
    p = path(pid)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8")); d["time_right"] = int(time_right)
        p.write_text(json.dumps(d, indent=1), encoding="utf-8")