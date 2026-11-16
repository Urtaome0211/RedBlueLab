# -*- coding: utf-8 -*-
"""通用自绘控件：号码球、注卡、指标块。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, PushButton,
                            StrongBodyLabel, ToolButton)

from ..core.recommend import Ticket

RED = "#E1251B"
RED_DARK = "#B01A12"
BLUE = "#1F6FD0"


def ball_font(size: int) -> QFont:
    f = QFont()
    f.setPointSizeF(max(8.0, size * 0.36))
    f.setWeight(QFont.DemiBold)
    return f


class Ball(QLabel):
    """单个号码球。"""

    def __init__(self, number: int, kind: str = "red", size: int = 34,
                 parent: QWidget | None = None) -> None:
        super().__init__(f"{number:02d}", parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(ball_font(size))
        bg = RED if kind == "red" else BLUE
        self.setStyleSheet(
            f"background:{bg}; color:#FFFFFF; border-radius:{size // 2}px;"
            f" border:1px solid {RED_DARK if kind == 'red' else '#155AA8'};"
        )
        self.setToolTip(f"{'红' if kind == 'red' else '蓝'}球 {number:02d}")


class BallLine(QWidget):
    """一行号码：6 红（可选 + 蓝球）。"""

    def __init__(self, reds, blue: int | None, size: int = 34,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6 if size >= 30 else 4)
        for n in reds:
            lay.addWidget(Ball(int(n), "red", size))
        if blue is not None:
            plus = QLabel("+")
            plus.setStyleSheet("color:#8A8A8A;font-weight:600;")
            lay.addWidget(plus)
            lay.addWidget(Ball(int(blue), "blue", size))
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


class TicketCard(CardWidget):
    """一注号码卡片：序号 + 号码 + 形态 + 理由 + 复制。"""

    def __init__(self, ticket: Ticket, index: int, show_score: bool = False,
                 show_blue: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ticket = ticket
        self.setBorderRadius(10)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(14)

        idx = StrongBodyLabel(f"{index:02d}", self)
        idx.setFixedWidth(28)
        idx.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        idx.setStyleSheet("color:#7A7A7A;")
        lay.addWidget(idx, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        mid.addWidget(BallLine(ticket.reds, ticket.blue if show_blue else None, 34, self))

        meta = CaptionLabel(ticket.composition, self)
        meta.setStyleSheet("color:#8A8A8A;")
        mid.addWidget(meta)

        extra = ticket.reason or ""
        if extra.startswith(ticket.composition):
            extra = extra[len(ticket.composition):].lstrip("；; ")
        if extra:
            reason = CaptionLabel("理由：" + extra, self)
            reason.setStyleSheet("color:#9A9A9A;")
            reason.setWordWrap(True)
            mid.addWidget(reason)

        lay.addLayout(mid, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        if show_score:
            score = CaptionLabel(f"评分 {ticket.score:.2f}", self)
            score.setStyleSheet("color:#8A8A8A;")
            score.setAlignment(Qt.AlignRight)
            right.addWidget(score)
        right.addStretch(1)
        self.copy_btn = PushButton("复制", self)
        self.copy_btn.setFixedWidth(64)
        self.copy_btn.clicked.connect(self._copy)
        right.addWidget(self.copy_btn, 0, Qt.AlignRight)
        lay.addLayout(right, 0)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.ticket.text)
        self.copy_btn.setText("已复制")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("复制"))


class StatBlock(QWidget):
    """竖向指标块：数值 + 说明。"""

    def __init__(self, value: str, caption: str, color: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.value_label = StrongBodyLabel(value, self)
        if color:
            self.value_label.setStyleSheet(f"color:{color};")
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lay.addWidget(self.value_label)
        cap = CaptionLabel(caption, self)
        cap.setStyleSheet("color:#8A8A8A;")
        lay.addWidget(cap)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet("background: rgba(128,128,128,0.18); border: none;")


def section_title(text: str, parent: QWidget | None = None) -> BodyLabel:
    label = BodyLabel(text, parent)
    label.setStyleSheet("color:#8A8A8A;font-weight:600;")
    return label


def muted(text: str, parent: QWidget | None = None) -> CaptionLabel:
    label = CaptionLabel(text, parent)
    label.setStyleSheet("color:#8A8A8A;")
    return label


def color_for_red() -> QColor:
    return QColor(RED)


def color_for_blue() -> QColor:
    return QColor(BLUE)


SPIN_QSS = """
QSpinBox {
    background: #FFFFFF;
    border: 1px solid #E2E2E2;
    border-radius: 5px;
    padding: 0 2px 0 4px;
    min-height: 31px;
    color: #1B1B1B;
    selection-background-color: #C00000;
}
QSpinBox:hover { border-color: #C9C9C9; }
QSpinBox:focus { border-color: #C00000; }
QSpinBox::up-button, QSpinBox::down-button {
    width: 16px; background: transparent; border: none;
}
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
"""


def number_spin(minimum: int = 0, maximum: int = 100, value: int = 0,
                width: int = 92, suffix: str = "",
                parent: QWidget | None = None) -> QSpinBox:
    """用原生 QSpinBox 加 Fluent 风格样式，避免 Fluent SpinBox 的行编辑宽度异常。"""
    spin = QSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    if suffix:
        spin.setSuffix(suffix)
    spin.setFixedWidth(width)
    spin.setAlignment(Qt.AlignCenter)
    spin.setButtonSymbols(QSpinBox.UpDownArrows)
    spin.setStyleSheet(SPIN_QSS)
    return spin


__all__ = ["Ball", "BallLine", "TicketCard", "StatBlock", "Divider", "section_title",
           "muted", "ToolButton", "number_spin", "RED", "BLUE", "color_for_red",
           "color_for_blue"]
