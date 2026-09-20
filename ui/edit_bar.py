"""오버레이 배치 편집 툴바: 배율·투명도 조절, 저장/취소. 항상 위, 작은 창."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QDoubleSpinBox


class EditBar(QWidget):
    saved = Signal()
    cancelled = Signal()
    scale_changed = Signal(float)
    opacity_changed = Signal(float)
    stack = Signal()

    def __init__(self, scale=2.0, opacity=0.95, has_mirror=True):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setObjectName("card")
        v = QVBoxLayout(self); v.setContentsMargins(18, 14, 18, 14); v.setSpacing(10)
        t = QLabel("오버레이 배치 편집"); t.setObjectName("title"); v.addWidget(t)
        s = QLabel("점선 창을 드래그해 옮기세요 (항목마다 따로). 휠 = 배율.  Shift+드래그 / Shift+휠 = 전부 함께"); s.setObjectName("subtitle"); v.addWidget(s)

        row = QHBoxLayout(); row.setSpacing(10); v.addLayout(row)
        row.addWidget(QLabel("전체 배율"))
        self.scale = QDoubleSpinBox(); self.scale.setRange(0.5, 6.0); self.scale.setSingleStep(0.1); self.scale.setValue(scale); self.scale.setFixedWidth(80)
        self.scale.valueChanged.connect(self.scale_changed.emit); row.addWidget(self.scale)
        row.addWidget(QLabel("투명도"))
        self.opacity = QDoubleSpinBox(); self.opacity.setRange(0.2, 1.0); self.opacity.setSingleStep(0.05); self.opacity.setValue(opacity); self.opacity.setFixedWidth(80)
        self.opacity.valueChanged.connect(self.opacity_changed.emit); row.addWidget(self.opacity)
        st = QPushButton("세로로 정리"); st.setToolTip("첫 항목 아래로 나머지를 정렬"); st.clicked.connect(self.stack.emit); row.addWidget(st)
        row.addStretch()
        if not has_mirror:
            self.scale.setEnabled(False); self.opacity.setEnabled(False)

        btns = QHBoxLayout(); btns.addStretch(); v.addLayout(btns)
        c = QPushButton("취소"); c.clicked.connect(self.cancelled.emit); btns.addWidget(c)
        ok = QPushButton("저장"); ok.setObjectName("primary"); ok.clicked.connect(self.saved.emit); btns.addWidget(ok)
        self.adjustSize()
        self.move(40, 40)