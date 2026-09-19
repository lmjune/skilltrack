"""
설정 모델 + JSON 저장/불러오기. profiles/config.json 하나에 전부.

구조:
  general   fps, sound, diag_save (진단 프레임 저장), hotkeys
  regions   status: 상태창 캡처 영역 (클라이언트 기준). skill: 스킬창들 (3b 에서 채움)
  watches   {행번호: 알림 설정 + 라벨}  — 고정 섹션 행 기준
  overlays  alert 위치, mirror 위치/배율/행 옵션

코드 어디서도 숫자를 하드코딩하지 않고 여기서 읽는다. 설정 UI 는 이 파일을 편집하는 화면이다.
"""
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_FILE = ROOT / "profiles" / "config.json"


@dataclass
class General:
    window_title: str = "마비노기"
    fps: int = 5
    sound: bool = True
    diag_save: bool = True                 # 의심 프레임 자동 저장 (배포 기본값은 False)
    hotkey_toggle: str = "F9"
    hotkey_settings: str = "F10"
    hide_when_inactive: bool = True


@dataclass
class WatchCfg:
    label: str = ""                        # 비우면 "행N"
    enabled: bool = True
    alert_off: bool = True
    alert_on: bool = False
    alert_under: list = field(default_factory=lambda: [60, 30])
    alert_under_extended: list = field(default_factory=lambda: [120, 60])
    keep: bool = False
    keep_delay: float = 10.0
    keep_interval: float = 30.0
    sound_file: str = ""                   # 비우면 심각도별 비프


@dataclass
class MirrorRow:
    row: int
    icon: bool = True
    name: bool = True
    time: bool = True
    only_active: bool = False
    dim_inactive: bool = True


@dataclass
class Overlays:
    alert_pos: list = field(default_factory=lambda: [1500, 1500])
    alert_width: int = 520
    alert_font_pt: int = 18
    mirror_pos: list = field(default_factory=lambda: [1500, 1300])
    mirror_scale: float = 2.0
    mirror_opacity: float = 0.95
    mirror_rows: list = field(default_factory=list)      # [MirrorRow]


@dataclass
class Regions:
    status: list | None = None            # [x, y, w, h] 클라이언트 기준. None 이면 미설정
    skill: list = field(default_factory=list)   # 3b: [{"id":..., "rect":[...], "grid":{...}}]


@dataclass
class Config:
    general: General = field(default_factory=General)
    regions: Regions = field(default_factory=Regions)
    watches: dict = field(default_factory=dict)          # {row(int): WatchCfg}
    overlays: Overlays = field(default_factory=Overlays)

    # ------------------------------------------------------------ 저장/로드
    def save(self, path=CONFIG_FILE):
        d = asdict(self)
        d["watches"] = {str(k): v for k, v in d["watches"].items()}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path=CONFIG_FILE):
        p = Path(path)
        if not p.exists():
            return cls()
        d = json.loads(p.read_text(encoding="utf-8"))
        c = cls()
        c.general = General(**{k: v for k, v in d.get("general", {}).items() if k in General.__dataclass_fields__})
        rg = d.get("regions", {})
        c.regions = Regions(status=rg.get("status"), skill=rg.get("skill", []))
        c.watches = {int(k): WatchCfg(**{kk: vv for kk, vv in v.items() if kk in WatchCfg.__dataclass_fields__})
                     for k, v in d.get("watches", {}).items()}
        ov = d.get("overlays", {})
        rows = [MirrorRow(**{k: v for k, v in r.items() if k in MirrorRow.__dataclass_fields__}) for r in ov.get("mirror_rows", [])]
        c.overlays = Overlays(**{k: v for k, v in ov.items() if k in Overlays.__dataclass_fields__ and k != "mirror_rows"}, mirror_rows=rows)
        return c

    # ------------------------------------------------------------ 편의
    def watch(self, row: int) -> WatchCfg:
        return self.watches.setdefault(row, WatchCfg())

    def watch_opts(self) -> dict:
        """Session 에 넘길 {row: Watch 필드} (enabled 인 것만)"""
        out = {}
        for row, w in self.watches.items():
            if not w.enabled:
                continue
            out[row] = dict(label=w.label or f"행{row}", alert_off=w.alert_off, alert_on=w.alert_on,
                            alert_under=list(w.alert_under), alert_under_extended=list(w.alert_under_extended),
                            keep=w.keep, keep_delay=w.keep_delay, keep_interval=w.keep_interval)
        return out