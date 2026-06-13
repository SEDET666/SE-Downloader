"""
CollapsibleSettingGroup — Fluent Design 风格的可折叠设置分组。

展开时 header + content 合成一个完整圆角卡片：
  ┌──────────────────────────────────┐  ← 圆角顶部
  │ ⚙  标题                      ∨  │  ← header（点击折叠/展开）
  ├──────────────────────────────────┤  ← 分隔线
  │  [Setting Card 1]                │
  │  [Setting Card 2]                │  ← content 区，白色背景
  └──────────────────────────────────┘  ← 圆角底部

折叠时只显示 header 单独的圆角卡片。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QGraphicsOpacityEffect
)
from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QSize, Property, QByteArray, Signal
)
from PySide6.QtGui import QPainter, QColor, QPen
from qfluentwidgets import (
    CardWidget, BodyLabel, TransparentToolButton,
    FluentIcon, isDarkTheme
)


class _Arrow(QWidget):
    """Rotating chevron arrow (0° = pointing right/collapsed, 90° = down/expanded)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._angle = 0.0

    def get_angle(self): return self._angle
    def set_angle(self, v):
        self._angle = v
        self.update()
    angle = Property(float, get_angle, set_angle)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor("#ffffff" if isDarkTheme() else "#555555")
        pen = QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.translate(8, 8)
        p.rotate(self._angle)
        p.drawLine(-3, -4,  3,  0)
        p.drawLine( 3,  0, -3,  4)
        p.end()


class _GroupCard(QWidget):
    """
    Custom card that renders header + optional content as one rounded card,
    with a divider between them and correct corner rounding.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # We paint our own background to match CardWidget style
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._update_style()

    def _update_style(self):
        if isDarkTheme():
            bg      = "#2d2d2d"
            border  = "#3a3a3a"
            divider = "#3a3a3a"
        else:
            bg      = "#ffffff"
            border  = "#e5e5e5"
            divider = "#ebebeb"
        self.setStyleSheet(f"""
            _GroupCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.StyleChange:
            self._update_style()


class CollapsibleSettingGroup(QWidget):
    """
    Fluent-style collapsible settings group.
    Header and content share one card background when expanded.
    """

    expanded_changed = Signal(bool)

    def __init__(self, icon, title: str, parent=None, expanded: bool = True):
        super().__init__(parent)
        self._expanded = expanded
        self._cards: list = []
        self._anim_arrow = None
        self._anim_fade  = None
        self._setup_ui(icon, title)
        if not expanded:
            self._content_wrap.setVisible(False)
            self._arrow.set_angle(0.0)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _setup_ui(self, icon, title: str):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Outer card (the white rounded rectangle) ──────────────────────────
        self._card = QWidget(self)
        self._card.setObjectName("collapsibleCard")
        card_vl = QVBoxLayout(self._card)
        card_vl.setContentsMargins(0, 0, 0, 0)
        card_vl.setSpacing(0)
        outer.addWidget(self._card)

        # Update card background on theme change
        self._apply_card_style()

        # ── Header row (always visible) ───────────────────────────────────────
        self._header = QWidget(self._card)
        self._header.setFixedHeight(48)
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.mousePressEvent = lambda e: self._toggle()
        self._header.setObjectName("collapsibleHeader")

        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(10)

        self._icon_btn = TransparentToolButton(icon)
        self._icon_btn.setIconSize(QSize(16, 16))
        self._icon_btn.setFixedSize(28, 28)
        self._icon_btn.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(self._icon_btn)

        self._title_lbl = BodyLabel(title)
        hl.addWidget(self._title_lbl, stretch=1)

        self._arrow = _Arrow(self._header)
        hl.addWidget(self._arrow)

        card_vl.addWidget(self._header)

        # ── Divider line ──────────────────────────────────────────────────────
        self._divider = QFrame(self._card)
        self._divider.setFrameShape(QFrame.Shape.HLine)
        self._divider.setVisible(self._expanded)
        self._update_divider_style()
        card_vl.addWidget(self._divider)

        # ── Content wrapper ───────────────────────────────────────────────────
        self._content_wrap = QWidget(self._card)
        self._content_wrap.setVisible(self._expanded)
        cl = QVBoxLayout(self._content_wrap)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self._content_layout = cl
        card_vl.addWidget(self._content_wrap)

        self._arrow.set_angle(90.0 if self._expanded else 0.0)

    def _apply_card_style(self):
        if isDarkTheme():
            bg, border = "#2d2d2d", "#3d3d3d"
        else:
            bg, border = "#ffffff", "#e5e5e5"
        self._card.setStyleSheet(f"""
            QWidget#collapsibleCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QWidget#collapsibleHeader {{
                background: transparent;
                border-radius: 8px;
            }}
        """)

    def _update_divider_style(self):
        color = "#3d3d3d" if isDarkTheme() else "#ebebeb"
        self._divider.setStyleSheet(f"QFrame {{ color: {color}; }}")

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.StyleChange:
            self._apply_card_style()
            self._update_divider_style()

    # ── Public API ────────────────────────────────────────────────────────────

    def addCard(self, card: QWidget):
        self._cards.append(card)
        # Remove any border-radius from child cards so they blend into group card
        card.setStyleSheet(card.styleSheet() + """
            CardWidget, QFrame[frameShape="0"] {
                border-radius: 0px;
                border: none;
                border-bottom: 1px solid transparent;
            }
        """)
        self._content_layout.addWidget(card)

    def addSettingCard(self, card: QWidget):
        self.addCard(card)

    def setTitle(self, title: str):
        self._title_lbl.setText(title)

    def expand(self):
        if not self._expanded: self._toggle()

    def collapse(self):
        if self._expanded: self._toggle()

    # ── Toggle animation ──────────────────────────────────────────────────────

    def _toggle(self):
        self._expanded = not self._expanded
        self.expanded_changed.emit(self._expanded)

        # Arrow animation
        anim = QPropertyAnimation(self._arrow, QByteArray(b"angle"))
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(0.0  if self._expanded else 90.0)
        anim.setEndValue(  90.0 if self._expanded else 0.0)
        anim.start()
        self._anim_arrow = anim

        if self._expanded:
            self._divider.setVisible(True)
            self._content_wrap.setVisible(True)
        else:
            # Fade out then hide
            effect = QGraphicsOpacityEffect(self._content_wrap)
            self._content_wrap.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, QByteArray(b"opacity"))
            fade.setDuration(130)
            fade.setStartValue(1.0)
            fade.setEndValue(0.0)
            def _hide_content():
                self._content_wrap.setVisible(False)
                self._divider.setVisible(False)
                self._content_wrap.setGraphicsEffect(None)
            fade.finished.connect(_hide_content)
            fade.start()
            self._anim_fade = fade
