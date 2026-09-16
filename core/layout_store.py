"""
상태창 레이아웃 저장/복원.

고정 섹션은 안 움직인다는 전제. 한 번 검출한 행 좌표와 이름 지문을 저장해두고,
다음 시작 때는 저장된 좌표에서 지문만 검증한다. 통과하면 검출을 건너뛴다.
(검출은 배경에 영향을 받는 가장 취약한 단계라, 실행 중엔 절대 다시 하지 않는다)
"""
import base64
import json
from pathlib import Path

from core.rows import Row, RowLayout
from core.status import parse_rows, fp_same
from core.pixelwatch import NameSite, make_site


def save(path, layout: RowLayout, states, rect, frame=None):
    """rect: 캡처 영역 (클라이언트 기준 x, y, w, h). states: parse_rows 결과. frame: 획 자리 저장용."""
    pinned = set(layout.sections[0]) if layout.sections else set()
    by = {s.index: s for s in states}
    rows = []
    for i in sorted(pinned):
        if i not in by:
            continue
        s = by[i]
        d = {"index": i, "icon": list(layout.rows[i].icon), "text": list(layout.rows[i].text),
             "name_fp": base64.b64encode(s.name_fp).decode()}
        if frame is not None and s.name_range is not None:
            d["site"] = make_site(frame, layout.rows[i].text, s.name_range).to_json()
        rows.append(d)
    data = {"rect": list(rect), "pitch": layout.pitch, "right": layout.right,
            "time_right": layout.time_right, "rows": rows}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")


def load(path):
    """(rect, layout, {index: name_fp}, {index: NameSite}) 또는 None"""
    p = Path(path)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = [Row(y=r["icon"][1], icon=tuple(r["icon"]), text=tuple(r["text"])) for r in d["rows"]]
    layout = RowLayout(pitch=d["pitch"], icon_x=rows[0].icon[0], icon_w=rows[0].icon[2],
                       icon_h=rows[0].icon[3], text_x=rows[0].text[0],
                       right=d.get("right", rows[0].text[0] + rows[0].text[2]), rows=rows,
                       sections=[list(range(len(rows)))], time_right=d.get("time_right"))
    fps = {i: base64.b64decode(r["name_fp"]) for i, r in enumerate(d["rows"])}
    sites = {i: NameSite.from_json(r["site"]) for i, r in enumerate(d["rows"]) if "site" in r}
    return tuple(d["rect"]), layout, fps, sites


def verify(frame, layout: RowLayout, fps: dict) -> float:
    """저장된 좌표에서 파싱했을 때 지문이 맞는 행의 비율 (0~1)."""
    states = parse_rows(frame, layout)
    got = {s.index: s.name_fp for s in states}
    ok = sum(1 for i, fp in fps.items() if i in got and fp_same(got[i], fp))
    return ok / max(1, len(fps))


def update_time_right(path, time_right):
    """시간 끝 열을 처음 알게 됐을 때 저장본에 기록."""
    p = Path(path)
    d = json.loads(p.read_text(encoding="utf-8"))
    d["time_right"] = int(time_right)
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")