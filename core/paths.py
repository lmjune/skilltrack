"""
경로 한 곳에서. 소스로 실행할 때와 PyInstaller exe 로 실행할 때가 다르다.

  ASSETS   읽기 전용 자산 (glyphs.json, boss_icons/, sounds/, fonts/)
           소스: <repo>/assets           exe: <dist>/_internal/assets  (번들)
  DATA     사용자 데이터 (profiles/, 진단 프레임 diag/, 모르는 글자 unknown/)
           소스: <repo>                  exe: exe 옆 폴더 (업데이트해도 남는다)
  VERSION  홈 부제목·로그에 표시
"""
import sys
from pathlib import Path

VERSION = "0.9.0"
APP_NAME = "마비오라"        # 표시 이름 (창 제목·트레이). 저장소/모듈 이름은 skilltrack 그대로
EXE_NAME = "mabiaura"       # exe·로그 파일 이름
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    ASSETS = Path(sys._MEIPASS) / "assets"          # onedir 에선 <dist>/_internal
    DATA = Path(sys.executable).parent
else:
    ROOT = Path(__file__).parent.parent
    ASSETS = ROOT / "assets"
    DATA = ROOT

PROFILES = DATA / "profiles"
DIAG = DATA / ("diag" if FROZEN else "tests/fixtures")     # 소스에선 기존 위치 유지 (tests/fixtures/auto, boss/auto)
UNKNOWN_DIR = DATA / ("diag/unknown" if FROZEN else "assets/unknown")