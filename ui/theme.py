"""
공용 테마. 어두운 배경 + 카드 + 강조색 하나. 모든 설정 창이 apply(app) 로 같은 룩을 쓴다.
objectName 으로 역할을 구분한다: card, title, subtitle, muted, primary(버튼), ghost(버튼), thumb, footer
"""
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from core.paths import ASSETS
FONT_DIR = ASSETS / "fonts"   # Pretendard-*.ttf 를 여기 두면 자동 로드 (OFL)

BG, CARD, CARD_HOVER, BORDER = "#0f1115", "#171a20", "#1c2028", "#262b35"
TEXT, MUTED, ACCENT, ACCENT_DIM, DANGER = "#e6e8ec", "#8b919c", "#5b8cff", "#3a5bb8", "#ff5b5b"

QSS = f"""
* {{ font-family: "Pretendard", "Malgun Gothic", "Segoe UI", sans-serif; font-size: 13px; color: {TEXT}; }}
QWidget {{ background: {BG}; }}
QScrollArea {{ border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QLabel#title {{ font-size: 20px; font-weight: 700; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 13px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}

QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#card:hover {{ background: {CARD_HOVER}; }}
QFrame#card QWidget {{ background: transparent; }}
QLabel#thumb {{ background: #0b0d11; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QFrame#divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

QLineEdit, QSpinBox, QDoubleSpinBox {{
  background: #0b0d11; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit#ghost {{ background: transparent; border: 1px solid transparent; font-size: 15px; font-weight: 600; }}
QLineEdit#ghost:hover, QLineEdit#ghost:focus {{ border-color: {BORDER}; background: #0b0d11; }}

QCheckBox {{ spacing: 10px; padding: 4px 0; }}
QCheckBox::indicator {{ width: 36px; height: 20px; border-radius: 10px; background: {BORDER}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QCheckBox::indicator:disabled {{ background: #1c2028; }}
QCheckBox:disabled {{ color: {MUTED}; }}
QCheckBox#small::indicator {{ width: 16px; height: 16px; border-radius: 4px; }}

QPushButton {{ background: transparent; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ background: {CARD_HOVER}; border-color: {MUTED}; }}
QPushButton:disabled {{ color: #4a4f5a; border-color: #1c2028; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; padding: 9px 22px; }}
QPushButton#primary:hover {{ background: #6d9aff; }}
QPushButton#ghost {{ border: none; color: {MUTED}; padding: 4px 8px; }}
QPushButton#ghost:hover {{ color: {TEXT}; background: transparent; }}
QPushButton#ghost:checked {{ color: {ACCENT}; }}

QGroupBox {{ border: 1px solid {BORDER}; border-radius: 12px; margin-top: 14px; padding: 12px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {MUTED}; }}
QMessageBox QLabel {{ background: transparent; }}
QWidget#footer {{ background: {CARD}; border-top: 1px solid {BORDER}; }}
"""


def apply(app: QApplication):
    app.setStyle("Fusion")
    if FONT_DIR.exists():
        for f in FONT_DIR.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(f))
    app.setStyleSheet(QSS)
    for fam in ("Pretendard", "Malgun Gothic", "Segoe UI"):
        if fam in QFontDatabase.families():
            app.setFont(QFont(fam, 10)); break