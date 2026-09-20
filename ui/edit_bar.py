"""오버레이 배치 편집 툴바: 배율·투명도 조절, 저장/취소. 항상 위, 작은 창."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QDoubleSpinBox


class EditBar(QWidget):
    saved = Signal()
    cancelled = Signal()
    scale_changed = Signal(float)
    opacity_changed = Signal(float)
    stack = Signal()

    skill_scale_changed = Signal(float)
    skill_opacity_changed = Signal(float)
    skill_stack = Signal()

    def __init__(self, scale=2.0, opacity=0.95, has_mirror=True, skill_scale=2.0, skill_opacity=0.95, has_skill=False):
        super().__init__()
        # 보통 창(제목줄 있음) + 항상 위. 테두리 없는 Tool 창은 게임 위에서 클릭해도 활성화가 안 돼 입력을 못 받는 경우가 있다
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.setWindowTitle("배치 편집")
        self.setObjectName("card")
        v = QVBoxLayout(self); v.setContentsMargins(18, 14, 18, 14); v.setSpacing(10)
        t = QLabel("오버레이 배치 편집"); t.setObjectName("title"); v.addWidget(t)
        s = QLabel("점선 창을 드래그해 옮기세요 (항목마다 따로). 휠 = 배율.  Shift+드래그 / Shift+휠 = 전부 함께"); s.setObjectName("subtitle"); v.addWidget(s)

        self.scale, self.opacity = self._row(v, "버프 표시", scale, opacity, self.scale_changed, self.opacity_changed, self.stack, has_mirror)
        self.skill_scale, self.skill_opacity = self._row(v, "스킬 표시", skill_scale, skill_opacity, self.skill_scale_changed, self.skill_opacity_changed, self.skill_stack, has_skill)

        btns = QHBoxLayout(); btns.addStretch(); v.addLayout(btns)
        c = QPushButton("취소"); c.clicked.connect(self.cancelled.emit); btns.addWidget(c)
        ok = QPushButton("저장"); ok.setObjectName("primary"); ok.clicked.connect(self.saved.emit); btns.addWidget(ok)
        self.adjustSize()
        self.move(40, 40)

    @staticmethod
    def _row(v, label, scale, opacity, sig_scale, sig_opacity, sig_stack, enabled):
        row = QHBoxLayout(); row.setSpacing(10); v.addLayout(row)
        l = QLabel(label); l.setFixedWidth(70); row.addWidget(l)
        row.addWidget(QLabel("배율"))
        sc = QDoubleSpinBox(); sc.setRange(0.5, 6.0); sc.setSingleStep(0.1); sc.setValue(scale); sc.setFixedWidth(80); sc.valueChanged.connect(sig_scale.emit); row.addWidget(sc)
        row.addWidget(QLabel("투명도"))
        op = QDoubleSpinBox(); op.setRange(0.2, 1.0); op.setSingleStep(0.05); op.setValue(opacity); op.setFixedWidth(80); op.valueChanged.connect(sig_opacity.emit); row.addWidget(op)
        for w in (sc, op):
            w.setFocusPolicy(Qt.StrongFocus); w.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
        st = QPushButton("세로로 정리"); st.clicked.connect(sig_stack.emit); row.addWidget(st)
        if not enabled:
            hint = QLabel("표시 항목 없음 — " + ("감시 항목 → 설정 → '화면에 크게 표시'" if label == "버프 표시" else "스킬 표시에서 슬롯 체크"))
            hint.setObjectName("muted"); row.addWidget(hint)
        row.addStretch()
        for w in (sc, op, st):
            w.setEnabled(enabled)
        return sc, op