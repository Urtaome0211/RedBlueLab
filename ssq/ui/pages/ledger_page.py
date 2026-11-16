# -*- coding: utf-8 -*-
"""成绩单页：每次生成的推荐都会存档，开奖后结算中奖与盈亏。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout,
                               QHeaderView, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from qfluentwidgets import (CaptionLabel, CardWidget, FluentIcon as FIF, MessageBox,
                            PrimaryPushButton, PushButton, ScrollArea,
                            StrongBodyLabel, TitleLabel)

from ...core import ledger as ledger_mod
from ...core.store import DataStore

LEVEL_NAME = {1: "一等奖", 2: "二等奖", 3: "三等奖", 4: "四等奖", 5: "五等奖", 6: "六等奖"}


def _levels_text(levels: dict) -> str:
    if not levels:
        return "未中奖"
    parts = [f"{LEVEL_NAME.get(int(k), k)}×{v}" for k, v in sorted(levels.items())]
    return " ".join(parts)


class LedgerPage(ScrollArea):
    dataChanged = Signal()

    def __init__(self, store: DataStore, ledger: ledger_mod.Ledger,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ledgerPage")
        self.store = store
        self.ledger = ledger

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 32)
        self.vbox.setSpacing(14)

        self.vbox.addWidget(TitleLabel("推荐成绩单", self.view))
        sub = CaptionLabel(
            "每次生成推荐都会自动存档（相同号码不重复记录）。开奖后点「结算」，"
            "系统按官方奖金计算每一注的中奖金额。", self.view)
        sub.setStyleSheet("color:#8A8A8A;")
        sub.setWordWrap(True)
        self.vbox.addWidget(sub)

        self.vbox.addWidget(self._build_kpi())

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.settle_btn = PrimaryPushButton(FIF.COMPLETED, "结算已开奖的批次", self.view)
        self.settle_btn.clicked.connect(self.settle)
        refresh_btn = PushButton(FIF.SYNC, "刷新", self.view)
        refresh_btn.clicked.connect(self.reload)
        export_btn = PushButton(FIF.COPY, "复制成绩单", self.view)
        export_btn.clicked.connect(self.export_text)
        clear_btn = PushButton(FIF.DELETE, "清空", self.view)
        clear_btn.clicked.connect(self.clear)
        actions.addWidget(self.settle_btn)
        actions.addWidget(refresh_btn)
        actions.addWidget(export_btn)
        actions.addStretch(1)
        actions.addWidget(clear_btn)
        self.vbox.addLayout(actions)

        self.status = CaptionLabel("", self.view)
        self.status.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(self.status)

        self.table = QTableWidget(0, 8, self.view)
        self.table.setHorizontalHeaderLabels(
            ["生成时间", "基准期号", "算法", "注数", "投入", "结算期号", "中奖", "盈亏 / 结果"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(360)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        for col, width in enumerate((148, 96, 92, 62, 86, 100, 86)):
            self.table.setColumnWidth(col, width)
        self.table.setStyleSheet(
            "QTableWidget{background:#FFFFFF;border:1px solid #E6E6E6;"
            "border-radius:8px;alternate-background-color:#FAFAFA;}"
            "QTableWidget::item{padding:0 8px;}"
            "QHeaderView::section{background:#F5F5F5;border:none;"
            "border-bottom:1px solid #E6E6E6;padding:7px 8px;color:#5A5A5A;}")
        font = QApplication.font()
        self.table.setFont(font)
        self.table.horizontalHeader().setFont(font)
        self.table.verticalHeader().setFont(font)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.vbox.addWidget(self.table, 1)

        self.reload()

    # ------------------------------------------------ UI
    def _build_kpi(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(30)

        self.kpi_batches = self._kpi(lay, "批次", "0")
        self.kpi_tickets = self._kpi(lay, "总注数", "0")
        self.kpi_cost = self._kpi(lay, "投入", "0 元")
        self.kpi_prize = self._kpi(lay, "中奖", "0 元")
        self.kpi_profit = self._kpi(lay, "盈亏", "0 元")
        self.kpi_roi = self._kpi(lay, "返还率", "-")
        lay.addStretch(1)
        return card

    def _kpi(self, layout: QHBoxLayout, caption: str, value: str) -> StrongBodyLabel:
        box = QVBoxLayout()
        box.setSpacing(2)
        label = StrongBodyLabel(value, self.view)
        label.setStyleSheet("font-size:17px;")
        cap = CaptionLabel(caption, self.view)
        cap.setStyleSheet("color:#8A8A8A;")
        box.addWidget(label)
        box.addWidget(cap)
        layout.addLayout(box)
        return label

    # ------------------------------------------------ 数据
    def reload(self) -> None:
        self.ledger.load()
        stats = self.ledger.stats()
        self.kpi_batches.setText(f"{stats['settled_batches']} / {stats['batches']}")
        self.kpi_batches.setToolTip("已结算 / 全部批次")
        self.kpi_tickets.setText(f"{stats['tickets']}")
        self.kpi_cost.setText(f"{stats['cost']:,.0f} 元")
        self.kpi_prize.setText(f"{stats['prize']:,.0f} 元")
        profit = stats["profit"]
        self.kpi_profit.setText(f"{profit:+,.0f} 元")
        self.kpi_profit.setStyleSheet(
            f"font-size:17px;color:{'#C00000' if profit > 0 else ('#8A8A8A' if profit == 0 else '#2E7D32')};")
        self.kpi_roi.setText(f"{stats['roi']:.0%}" if stats["cost"] else "-")

        rows = self.ledger.recent(60)
        self.table.setRowCount(len(rows))
        for row, rec in enumerate(rows):
            settled = rec.get("settled")
            algo = {"stats": "统计打分", "random": "约束随机", "coverage": "覆盖优化"}.get(
                rec.get("kind", ""), rec.get("kind", "-"))
            result = "-" if not settled else _levels_text(settled.get("levels") or {})
            profit_cell = "-"
            if settled:
                profit_cell = f"{settled.get('prize', 0) - rec.get('cost', 0):+,.0f} 元 · {result}"
            values = [rec.get("created", "-"), rec.get("base_issue", "-"), algo,
                      f"{len(rec.get('tickets', []))}", f"{rec.get('cost', 0):,.0f} 元",
                      (settled or {}).get("issue", "待开奖"),
                      f"{(settled or {}).get('prize', 0):,.0f} 元" if settled else "-",
                      profit_cell]
            for col, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(
                    (Qt.AlignRight | Qt.AlignVCenter) if col in (3, 4, 6)
                    else (Qt.AlignLeft | Qt.AlignVCenter))
                if settled:
                    item.setToolTip("；".join(f"{t}" for t in rec.get("reds_text", [])))
                self.table.setItem(row, col, item)

        if rows:
            self.status.setText(
                f"共 {stats['batches']} 批（已结算 {stats['settled_batches']}，"
                f"待开奖 {stats['pending_batches']}）· 中奖 {stats['winning_tickets']} 注")
        else:
            self.status.setText("还没有记录：在「号码推荐」页生成推荐时勾选「记入成绩单」。")

    def settle(self) -> None:
        try:
            n = self.ledger.settle(self.store)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"结算失败：{exc}")
            return
        self.reload()
        if n:
            self.status.setText(f"已结算 {n} 批 · " + self.status.text())
        else:
            self.status.setText("没有需要结算的批次（等最新一期开奖后再试）")

    def export_text(self) -> None:
        QApplication.clipboard().setText(ledger_mod.export_text(self.ledger))
        self.status.setText("成绩单已复制到剪贴板")

    def clear(self) -> None:
        if not self.ledger.records:
            return
        box = MessageBox("清空成绩单", "所有存档记录都会删除，且无法恢复。确定继续？", self)
        box.yesButton.setText("清空")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        self.ledger.clear()
        self.reload()
        self.status.setText("成绩单已清空")
        self.dataChanged.emit()

