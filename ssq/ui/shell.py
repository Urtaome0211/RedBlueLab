# -*- coding: utf-8 -*-
"""彩种外壳：一个彩种一个导航项，页面内用下拉框切换「推荐 / 历史 / 走势 …」。

这样侧栏从「20 个平铺页面」变成「8 个彩种 + 设置」，找起来更清楚。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import CaptionLabel, ComboBox, StrongBodyLabel, setFont


class GameShell(QWidget):
    """把同一彩种的多个页面收进一个容器，用顶部下拉框切换。"""

    def __init__(self, title: str, modules: list[tuple[str, QWidget]], parent=None):
        super().__init__(parent)
        self.title = title
        self.modules = modules
        self.setObjectName(f"shell_{abs(hash(title)) & 0xFFFF:x}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        row = QHBoxLayout(header)
        row.setContentsMargins(36, 18, 36, 6)
        row.setSpacing(10)

        name = StrongBodyLabel(title, header)
        setFont(name, 15)
        row.addWidget(name)

        row.addStretch(1)

        row.addWidget(CaptionLabel("模块", header))
        self.combo = ComboBox(header)
        self.combo.addItems([label for label, _ in modules])
        self.combo.setFixedWidth(132)
        self.combo.currentIndexChanged.connect(self._on_changed)
        row.addWidget(self.combo)
        outer.addWidget(header)

        self.stack = QStackedWidget(self)
        for _, widget in modules:
            self.stack.addWidget(widget)
        outer.addWidget(self.stack, 1)

        if modules:
            self._on_changed(0)

    # ---------------------------------------------------------------- api
    def select(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.combo.setCurrentIndex(index)

    def show_page(self, widget: QWidget) -> bool:
        """切到包含 widget 的模块，供截图脚本 / 自检使用。"""
        for i, (_, page) in enumerate(self.modules):
            if page is widget:
                self.select(i)
                return True
        return False

    def current_module(self) -> QWidget | None:
        return self.stack.currentWidget()

    def shutdown(self) -> None:
        for _, page in self.modules:
            hook = getattr(page, "shutdown", None)
            if callable(hook):
                try:
                    hook()
                except Exception:      # noqa: BLE001 - 退出阶段不让异常打断
                    pass

    # ---------------------------------------------------------------- 内部
    def _hints(self) -> dict[str, str]:
        return {
            "推荐": "基于历史统计生成，不能提高中奖概率",
            "成绩单": "自动记录每次推荐，开奖后结算盈亏",
            "筛选器": "按条件过滤全部组合，看看还剩多少注",
            "历史": "往期开奖明细，双击可在浏览器查看官网公告",
            "走势": "频次与和值分布，偏差属于随机波动",
        }

    def _on_changed(self, index: int) -> None:
        if not (0 <= index < self.stack.count()):
            return
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        hook = getattr(page, "on_show", None)
        if callable(hook):
            try:
                hook()
            except Exception:      # noqa: BLE001
                pass
