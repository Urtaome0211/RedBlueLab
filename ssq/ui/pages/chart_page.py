# -*- coding: utf-8 -*-
"""走势图页：和值走势 / 红球频次 / 蓝球频次 / 遗漏。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

import pyqtgraph as pg
from qfluentwidgets import (CaptionLabel, CardWidget, SegmentedWidget,
                            TitleLabel, ScrollArea)

from ...core.store import BLUE_MAX, RED_MAX, DataStore
from ..widgets import BLUE, RED

pg.setConfigOptions(antialias=True)

CHART_RED = "#D1433B"
CHART_BLUE = "#2F7FD0"
GRID = (150, 150, 150, 60)
TEXT = "#7A7A7A"


class ChartPage(ScrollArea):
    def __init__(self, store: DataStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartPage")
        self.store = store
        self.current = "sum"

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 28)
        self.vbox.setSpacing(14)

        self.vbox.addWidget(TitleLabel("走势与分布", self.view))
        self.hint = CaptionLabel("数据来自本地数据集，抓取新开奖后会自动刷新", self.view)
        self.hint.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(self.hint)

        self.segment = SegmentedWidget(self.view)
        self.segment.addItem("sum", "和值走势", onClick=lambda: self._switch("sum"))
        self.segment.addItem("red", "红球频次", onClick=lambda: self._switch("red"))
        self.segment.addItem("blue", "蓝球频次", onClick=lambda: self._switch("blue"))
        self.segment.addItem("omit", "当前遗漏", onClick=lambda: self._switch("omit"))
        self.segment.setCurrentItem("sum")
        self.vbox.addWidget(self.segment)

        card = CardWidget(self.view)
        card.setBorderRadius(10)
        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(8, 8, 8, 8)
        self.plot = pg.PlotWidget(background="#FFFFFF", parent=card)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.showGrid(x=False, y=True, alpha=0.25)
        for axis in ("left", "bottom"):
            ax = self.plot.getAxis(axis)
            ax.setTextPen(pg.mkPen(TEXT))
            ax.setPen(pg.mkPen(GRID))
        card_lay.addWidget(self.plot)
        self.vbox.addWidget(card, 1)

        self.caption = CaptionLabel("", self.view)
        self.caption.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(self.caption)

        self.reload()

    # ------------------------------------------------ 切换
    def _switch(self, key: str) -> None:
        self.current = key
        self.reload()

    def select(self, key: str) -> None:
        """外部切换图表（同步分段控件的选中态）。"""
        if key not in ("sum", "red", "blue", "omit"):
            return
        self.segment.setCurrentItem(key)
        self._switch(key)

    # ------------------------------------------------ 绘制
    def reload(self) -> None:
        self.plot.clear()
        if not self.store.available:
            self.plot.setTitle("暂无数据", color=TEXT, size="11pt")
            self.caption.setText("请先在「推荐」页抓取开奖数据。")
            return
        getattr(self, f"_draw_{self.current}")()

    def _draw_sum(self) -> None:
        fs = self.store.features()
        n = len(fs.sums)
        k = min(120, n)
        sums = fs.sums[-k:]
        issues = self.store.df["期号"].tolist()[:k][::-1]

        x = np.arange(k)
        curve = self.plot.plot(x, sums, pen=pg.mkPen(CHART_RED, width=2),
                               symbol="o", symbolSize=4,
                               symbolBrush=pg.mkBrush(CHART_RED),
                               symbolPen=None)
        _ = curve
        mean = float(sums.mean())
        p10, p90 = np.percentile(sums, [10, 90])
        for value, style, label in ((mean, Qt.DashLine, f"均值 {mean:.0f}"),
                                    (p10, Qt.DotLine, f"P10 {p10:.0f}"),
                                    (p90, Qt.DotLine, f"P90 {p90:.0f}")):
            line = pg.InfiniteLine(pos=value, angle=0,
                                   pen=pg.mkPen(CHART_BLUE, width=1, style=style),
                                   label=label, labelOpts={"position": 0.92,
                                                           "color": CHART_BLUE,
                                                           "movable": False})
            self.plot.addItem(line)

        ticks = [(i, str(issues[i])[4:]) for i in range(0, k, max(1, k // 8))]
        self.plot.getAxis("bottom").setTicks([ticks])
        self.plot.setTitle(f"最近 {k} 期红球和值", color=TEXT, size="10pt")
        self.caption.setText(
            f"全量 {n} 期：均值 {fs.mean_sum:.1f}，标准差 {fs.std_sum:.1f}；"
            f"最近 {k} 期落在 P10–P90（{p10:.0f}–{p90:.0f}）之间的占 "
            f"{np.mean((sums >= p10) & (sums <= p90)):.0%}"
        )

    def _draw_red(self) -> None:
        fs = self.store.features()
        counts = fs.red_count[1:RED_MAX + 1]
        bars = pg.BarGraphItem(x=np.arange(1, RED_MAX + 1), height=counts, width=0.72,
                               brush=pg.mkBrush(CHART_RED + "CC"),
                               pen=pg.mkPen(CHART_RED))
        self.plot.addItem(bars)
        expect = fs.n * 6 / RED_MAX
        self.plot.addItem(pg.InfiniteLine(pos=expect, angle=0,
                                          pen=pg.mkPen(CHART_BLUE, width=1, style=Qt.DashLine),
                                          label=f"理论 {expect:.0f}",
                                          labelOpts={"position": 0.06, "color": CHART_BLUE,
                                                     "movable": False}))
        self.plot.getAxis("bottom").setTicks(
            [[(i, f"{i:02d}") for i in range(1, RED_MAX + 1, 2)]])
        self.plot.setTitle(f"红球出现次数（{fs.n} 期）", color=TEXT, size="10pt")
        top = int(np.argmax(counts)) + 1
        low = int(np.argmin(counts)) + 1
        self.caption.setText(
            f"最多 {top:02d}（{int(counts[top - 1])} 次），最少 {low:02d}"
            f"（{int(counts[low - 1])} 次），理论期望 {expect:.1f} 次。"
            "偏差属于随机波动，不构成可预测规律。"
        )

    def _draw_blue(self) -> None:
        fs = self.store.features()
        counts = fs.blue_count[1:BLUE_MAX + 1]
        bars = pg.BarGraphItem(x=np.arange(1, BLUE_MAX + 1), height=counts, width=0.62,
                               brush=pg.mkBrush(CHART_BLUE + "CC"),
                               pen=pg.mkPen(CHART_BLUE))
        self.plot.addItem(bars)
        expect = fs.n / BLUE_MAX
        self.plot.addItem(pg.InfiniteLine(pos=expect, angle=0,
                                          pen=pg.mkPen(CHART_RED, width=1, style=Qt.DashLine),
                                          label=f"理论 {expect:.0f}",
                                          labelOpts={"position": 0.06, "color": CHART_RED,
                                                     "movable": False}))
        self.plot.getAxis("bottom").setTicks([[(i, f"{i:02d}") for i in range(1, BLUE_MAX + 1)]])
        self.plot.setTitle(f"蓝球出现次数（{fs.n} 期）", color=TEXT, size="10pt")
        top = int(np.argmax(counts)) + 1
        low = int(np.argmin(counts)) + 1
        self.caption.setText(
            f"最多 {top:02d}（{int(counts[top - 1])} 次），最少 {low:02d}"
            f"（{int(counts[low - 1])} 次），理论期望 {expect:.1f} 次。"
        )

    def _draw_omit(self) -> None:
        fs = self.store.features()
        om = fs.red_omission[1:RED_MAX + 1]
        bars = pg.BarGraphItem(x=np.arange(1, RED_MAX + 1), height=om, width=0.72,
                               brush=pg.mkBrush("#8E8E8EAA"), pen=pg.mkPen("#8E8E8E"))
        self.plot.addItem(bars)
        self.plot.getAxis("bottom").setTicks(
            [[(i, f"{i:02d}") for i in range(1, RED_MAX + 1, 2)]])
        self.plot.setTitle("红球当前遗漏（距最近一次开出）", color=TEXT, size="10pt")
        order = np.argsort(-om)[:3]
        text = "，".join(f"{int(i) + 1:02d} 号 {int(om[i])} 期" for i in order)
        self.caption.setText(f"遗漏最久：{text}。期望遗漏约 {RED_MAX / 6:.1f} 期，长遗漏常见。")

    def _draw_sum_placeholder(self) -> None:  # pragma: no cover
        pass
