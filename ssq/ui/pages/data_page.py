# -*- coding: utf-8 -*-
"""历史数据页：最近开奖表格 + 搜索 + 冷热号一览。"""
from __future__ import annotations

import os

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QTableView, QVBoxLayout, QWidget)

from qfluentwidgets import (CaptionLabel, CardWidget, ComboBox,
                            FluentIcon as FIF, PushButton, ScrollArea,
                            SearchLineEdit, StrongBodyLabel, TitleLabel)

from ... import paths
from ...core import recommend as rec
from ...core.store import DataStore
from ..helpers import fmt_money
from ..widgets import BLUE, RED, muted

COLUMNS = [
    ("期号", "期号", 92),
    ("开奖日期", "日期", 104),
    ("星期", "星期", 56),
    ("红球", "红球", 176),
    ("蓝球", "蓝球", 60),
    ("一等奖注数", "一等奖", 74),
    ("一等奖单注奖金(元)", "单注奖金", 110),
    ("销售金额(元)", "销售额", 110),
    ("奖池金额(元)", "奖池", 110),
]

MONEY_COLS = {"一等奖单注奖金(元)", "销售金额(元)", "奖池金额(元)"}


class DrawModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None) -> None:
        super().__init__(parent)
        self.df = df

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.df)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return COLUMNS[section][1]
        return section + 1

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter) if COLUMNS[index.column()][0] in ("星期", "蓝球") \
                else int(Qt.AlignVCenter | Qt.AlignLeft)
        if role == Qt.ForegroundRole:
            col = COLUMNS[index.column()][0]
            if col == "红球":
                return QColor(RED)
            if col == "蓝球":
                return QColor(BLUE)
            return None
        if role == Qt.ToolTipRole:
            row = self.df.iloc[index.row()]
            link = row.get("详情链接") or ""
            return f"{row['期号']} 期\n{link}" if link else f"{row['期号']} 期"
        if role != Qt.DisplayRole:
            return None

        col = COLUMNS[index.column()][0]
        value = self.df.iloc[index.row()].get(col)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "-"
        if col in MONEY_COLS:
            try:
                return f"{int(float(value)):,}"
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def set_df(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self.df = df
        self.endResetModel()


class DataPage(ScrollArea):
    def __init__(self, store: DataStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dataPage")
        self.store = store

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 28)
        self.vbox.setSpacing(14)

        self.vbox.addWidget(TitleLabel("历史开奖", self.view))
        self.hint = CaptionLabel("双击一行可在浏览器打开官网开奖公告", self.view)
        self.hint.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(self.hint)

        self.vbox.addWidget(self._build_toolbar())
        self.vbox.addWidget(self._build_table(), 1)
        self.vbox.addWidget(self._build_stats())

        self.reload()

    # ------------------------------------------------ 控件
    def _build_toolbar(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        self.search = SearchLineEdit(card)
        self.search.setPlaceholderText("搜索期号，如 2026 或 2026127")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.reload)
        lay.addWidget(self.search)

        self.range_combo = ComboBox(card)
        self.range_combo.addItems(["最近 50 期", "最近 100 期", "最近 500 期", "全部"])
        self.range_combo.setCurrentIndex(1)
        self.range_combo.setFixedWidth(130)
        self.range_combo.currentIndexChanged.connect(self.reload)
        lay.addWidget(self.range_combo)

        lay.addStretch(1)

        self.count_label = StrongBodyLabel("—", card)
        lay.addWidget(self.count_label)

        self.open_btn = PushButton(FIF.FOLDER, "数据目录", card)
        self.open_btn.clicked.connect(self._open_folder)
        lay.addWidget(self.open_btn)
        return card

    def _build_table(self) -> QTableView:
        self.table = QTableView(self.view)
        self.model = DrawModel(pd.DataFrame(columns=[c[0] for c in COLUMNS]))
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setStyleSheet(
            "QTableView{border:1px solid rgba(128,128,128,0.18);border-radius:8px;"
            "background:transparent;gridline-color:transparent;}"
            "QHeaderView::section{background:transparent;border:none;"
            "border-bottom:1px solid rgba(128,128,128,0.18);padding:6px;"
            "color:#8A8A8A;font-weight:600;}"
        )
        self.table.doubleClicked.connect(self._open_link)
        for i, (_, _, width) in enumerate(COLUMNS):
            self.table.setColumnWidth(i, width)
        return self.table

    def _build_stats(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(28)
        self.hot_label = muted("", card)
        self.hot_label.setWordWrap(True)
        lay.addWidget(self.hot_label)
        return card

    # ------------------------------------------------ 数据
    def reload(self) -> None:
        if not self.store.available:
            self.model.set_df(pd.DataFrame(columns=[c[0] for c in COLUMNS]))
            self.count_label.setText("无数据")
            self.hot_label.setText("请先在「推荐」页抓取开奖数据。")
            return

        df = self.store.df
        limits = [50, 100, 500, None]
        limit = limits[self.range_combo.currentIndex()]
        if limit:
            df = df.head(limit)

        text = self.search.text().strip()
        if text:
            df = df[df["期号"].astype(str).str.contains(text, na=False)]

        cols = [c[0] for c in COLUMNS] + ["详情链接"]
        self.model.set_df(df[cols].reset_index(drop=True))
        self.count_label.setText(f"显示 {len(df)} / {self.store.count} 期")
        self._update_hot()

    def _update_hot(self) -> None:
        hc = rec.hot_cold(self.store, top=4)
        red_hot = "  ".join(f"{n:02d}({c})" for n, c in hc["red_hot"])
        red_cold = "  ".join(f"{n:02d}({c})" for n, c in hc["red_cold"])
        blue_hot = "  ".join(f"{n:02d}({c})" for n, c in hc["blue_hot"])
        om = "  ".join(f"{n:02d}({c}期)" for n, c in hc["red_omission"])
        self.hot_label.setText(
            f"红球热号 {red_hot}　|　冷号 {red_cold}\n"
            f"蓝球热号 {blue_hot}　|　遗漏最长 {om}"
        )

    # ------------------------------------------------ 交互
    def _open_folder(self) -> None:
        path = paths.DATA_DIR
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_link(self, index) -> None:
        row = self.model.df.iloc[index.row()]
        link = str(row.get("详情链接") or "")
        if link:
            QDesktopServices.openUrl(QUrl(link))
