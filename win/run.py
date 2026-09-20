"""
실행 진입점. 트레이 아이콘이 생기고 거기서 모든 설정을 연다. 자세한 건 win/app.py.

  python win/run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from win.app import App

if __name__ == "__main__":
    sys.exit(App(sys.argv).exec())