# -*- coding: utf-8 -*-
"""大乐透界面：推荐 / 历史数据 / 走势图。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout,
                               QHeaderView, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import pyqtgraph as pg
from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, ComboBox,
                            FluentIcon as FIF, PrimaryPushButton, PushButton,
                            ScrollArea, SegmentedWidget, StrongBodyLabel,
                            TitleLabel)

from ssq.ui.helpers import fmt_money
from ssq.ui.widgets import (BLUE, RED, Ball, Divider, muted, number_spin,
                            section_title)

from . import BACK_MAX, FRONT_MAX, GAME_NAME
from . import build as dlt_build
from . import fetch as dlt_fetch
from . import recommend as rec
from .recommend import DltParams, DltTicket
from .store import DltStore, Draw

KINDS = [("stats", "统计打分"), ("random", "约束随机")]


def _vsep() -> QWidget:
    w = QWidget()
    w.setFixedWidth(1)
    w.setStyleSheet("background: rgba(128,128,128,0.18);")
    return w


# ---------------------------------------------------------------- 线程
class DltCrawlWorker(QThread):
    message = Signal(str)
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, store: DltStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store

    def run(self) -> None:  # noqa: D102
        try:
            before = set(self.store.issues())
            self.message.emit("正在抓取官网数据…")
            dlt_fetch.crawl(log=self.message.emit)
            self.message.emit("正在重建数据集…")
            dlt_build.build(log=self.message.emit)
            self.store.load(force=True)
            after = set(self.store.issues())
            new = sorted(after - before)
            self.succeeded.emit({"total": len(after), "new": new})
        except Exception as exc:  # noqa: BLE001 - 线程里要把异常带回界面
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- 卡片
class DltLastCard(CardWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBorderRadius(10)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(18)

        info = QVBoxLayout()
        info.setSpacing(4)
        self.issue_label = TitleLabel("—", self)
        self.date_label = CaptionLabel("等待数据…", self)
        self.date_label.setStyleSheet("color:#8A8A8A;")
        info.addWidget(self.issue_label)
        info.addWidget(self.date_label)
        info.addStretch(1)
        lay.addLayout(info)
        lay.addWidget(_vsep())

        self.balls_host = QWidget(self)
        self.balls_layout = QHBoxLayout(self.balls_host)
        self.balls_layout.setContentsMargins(0, 0, 0, 0)
        self.balls_layout.setSpacing(6)
        lay.addWidget(self.balls_host)
        lay.addStretch(1)

        stats = QHBoxLayout()
        stats.setSpacing(28)
        self.pool = self._stat(stats, "奖池")
        self.sales = self._stat(stats, "销量")
        self.first = self._stat(stats, "一等奖")
        lay.addLayout(stats)
        self.update_from(None)

    def _stat(self, layout: QHBoxLayout, caption: str) -> StrongBodyLabel:
        box = QVBoxLayout()
        box.setSpacing(2)
        value = StrongBodyLabel("-", self)
        cap = CaptionLabel(caption, self)
        cap.setStyleSheet("color:#8A8A8A;")
        box.addWidget(value)
        box.addWidget(cap)
        layout.addLayout(box)
        return value

    def update_from(self, draw: Draw | None) -> None:
        while self.balls_layout.count():
            item = self.balls_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if draw is None:
            self.issue_label.setText("无数据")
            self.date_label.setText("请先抓取开奖数据")
            for label in (self.pool, self.sales, self.first):
                label.setText("-")
            return
        self.issue_label.setText(f"{draw.issue} 期")
        self.date_label.setText(f"{draw.date}  周{draw.week}")
        for n in draw.front:
            self.balls_layout.addWidget(Ball(n, "red", 36, self.balls_host))
        plus = BodyLabel("+", self.balls_host)
        plus.setStyleSheet("color:#8A8A8A;font-weight:600;")
        self.balls_layout.addWidget(plus)
        for n in draw.back:
            self.balls_layout.addWidget(Ball(n, "blue", 36, self.balls_host))

        self.pool.setText(fmt_money(draw.pool))
        self.sales.setText(fmt_money(draw.sales))
        if draw.first_count is None:
            self.first.setText("-")
        elif draw.first_count == 0:
            self.first.setText("空开")
        else:
            self.first.setText(f"{draw.first_count} 注 / {fmt_money(draw.first_money)}")


class DltBallLine(QWidget):
    """5 个前区红球 + 2 个后区蓝球。"""

    def __init__(self, front, back, size: int = 34, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6 if size >= 30 else 4)
        for n in front:
            lay.addWidget(Ball(int(n), "red", size, self))
        plus = BodyLabel("+", self)
        plus.setStyleSheet("color:#8A8A8A;font-weight:600;")
        lay.addWidget(plus)
        for n in back:
            lay.addWidget(Ball(int(n), "blue", size, self))
        lay.addStretch(1)


class DltTicketCard(CardWidget):
    """一注大乐透：序号 + 号码 + 形态 + 理由 + 复制。"""

    def __init__(self, ticket: DltTicket, index: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ticket = ticket
        self.setBorderRadius(10)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(14)

        idx = StrongBodyLabel(f"{index:02d}", self)
        idx.setFixedWidth(28)
        idx.setStyleSheet("color:#7A7A7A;")
        lay.addWidget(idx, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        mid.addWidget(DltBallLine(ticket.front, ticket.back, 34, self))
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

        self.copy_btn = PushButton("复制", self)
        self.copy_btn.setFixedWidth(64)
        self.copy_btn.clicked.connect(self._copy)
        lay.addWidget(self.copy_btn, 0, Qt.AlignRight)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.ticket.text)
        self.copy_btn.setText("已复制")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("复制"))


# ---------------------------------------------------------------- 推荐页
class DltRecommendPage(ScrollArea):
    dataChanged = Signal()

    def __init__(self, store: DltStore, params: DltParams | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dltRecommendPage")
        self.store = store
        self.params = params or DltParams()
        self.worker: DltCrawlWorker | None = None
        self.tickets: list[DltTicket] = []

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 32)
        self.vbox.setSpacing(14)

        title = TitleLabel("大乐透推荐", self.view)
        subtitle = CaptionLabel(
            "前区 5/35 + 后区 2/12 · 基于历史开奖的统计组合，仅供娱乐参考", self.view)
        subtitle.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(title)
        self.vbox.addWidget(subtitle)

        self.latest_card = DltLastCard(self.view)
        self.vbox.addWidget(self.latest_card)
        self.vbox.addWidget(self._build_controls())

        self.status_label = CaptionLabel("就绪", self.view)
        self.status_label.setStyleSheet("color:#8A8A8A;padding-left:2px;")
        self.vbox.addWidget(self.status_label)

        host = QWidget(self.view)
        self.tickets_layout = QVBoxLayout(host)
        self.tickets_layout.setContentsMargins(0, 0, 0, 0)
        self.tickets_layout.setSpacing(10)
        self.vbox.addWidget(host)

        self.footer = CaptionLabel("", self.view)
        self.footer.setStyleSheet("color:#9A9A9A;")
        self.footer.setWordWrap(True)
        self.vbox.addWidget(self.footer)
        self.vbox.addStretch(1)

        self.refresh_latest()
        self._update_footer()

    # ------------------------------------------------ 控件
    def _build_controls(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(12)

        algo_box = QVBoxLayout()
        algo_box.setSpacing(4)
        algo_box.addWidget(muted("算法", card))
        self.kind_combo = ComboBox(card)
        self.kind_combo.addItems([label for _, label in KINDS])
        self.kind_combo.setFixedWidth(130)
        algo_box.addWidget(self.kind_combo)
        lay.addLayout(algo_box)

        count_box = QVBoxLayout()
        count_box.setSpacing(4)
        count_box.addWidget(muted("注数", card))
        self.count_spin = number_spin(1, 20, self.params.n_tickets, 88, parent=card)
        count_box.addWidget(self.count_spin)
        lay.addLayout(count_box)

        sum_box = QVBoxLayout()
        sum_box.setSpacing(4)
        sum_box.addWidget(muted("前区和值", card))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.sum_lo = number_spin(15, 165, self.params.sum_lo, 76, parent=card)
        self.sum_hi = number_spin(15, 165, self.params.sum_hi, 76, parent=card)
        row.addWidget(self.sum_lo)
        row.addWidget(muted("~", card))
        row.addWidget(self.sum_hi)
        sum_box.addLayout(row)
        lay.addLayout(sum_box)

        lay.addStretch(1)

        self.generate_btn = PrimaryPushButton(FIF.SYNC, "生成推荐", card)
        self.generate_btn.clicked.connect(self.generate)
        lay.addWidget(self.generate_btn)

        self.crawl_btn = PushButton(FIF.DOWNLOAD, "抓取新开奖", card)
        self.crawl_btn.clicked.connect(self.start_crawl)
        lay.addWidget(self.crawl_btn)
        return card

    # ------------------------------------------------ 数据
    def refresh_latest(self) -> None:
        self.latest_card.update_from(self.store.latest())

    def _update_footer(self) -> None:
        if not self.store.available:
            self.footer.setText("还没有数据：点击「抓取新开奖」从体彩官网拉取全部历史开奖。")
            return
        ev = rec.expected_value(self.store)
        s = self.store.summary()
        self.footer.setText(
            f"数据：{s['count']} 期（{s['first']} ~ {s['last']}）· 更新于 {s['updated']}　|　"
            f"全部 {ev['combos']:,} 种组合，每注 2 元，按历史奖金估算单注期望回报约 "
            f"{ev['ev_per_ticket']:.2f} 元（返还率 {ev['return_rate']:.1%}）。"
            "开奖号码独立随机，任何选号方法都不改变概率。"
        )

    # ------------------------------------------------ 生成
    def generate(self) -> None:
        if not self.store.available:
            self.status_label.setText("没有历史数据，请先抓取开奖数据")
            return
        p = self.params
        p.kind = KINDS[self.kind_combo.currentIndex()][0]
        p.n_tickets = self.count_spin.value()
        p.sum_lo = self.sum_lo.value()
        p.sum_hi = self.sum_hi.value()
        p.validate()
        tickets = rec.recommend(self.store, p.kind, p)
        self.tickets = tickets
        while self.tickets_layout.count():
            item = self.tickets_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, t in enumerate(tickets, 1):
            self.tickets_layout.addWidget(DltTicketCard(t, i, self.view))
        self.status_label.setText(
            f"{rec.describe_params(p)} · 已生成 {len(tickets)} 注")

    # ------------------------------------------------ 抓取
    def start_crawl(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.crawl_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.crawl_btn.setText("抓取中…")
        self.worker = DltCrawlWorker(self.store, self)
        self.worker.message.connect(self.status_label.setText)
        self.worker.succeeded.connect(self._on_crawl_done)
        self.worker.failed.connect(self._on_crawl_failed)
        self.worker.finished.connect(self._on_crawl_finished)
        self.worker.start()

    def _on_crawl_finished(self) -> None:
        self.crawl_btn.setEnabled(True)
        self.generate_btn.setEnabled(True)
        self.crawl_btn.setText("抓取新开奖")

    def _on_crawl_done(self, info: dict) -> None:
        self.refresh_latest()
        self._update_footer()
        new = info.get("new") or []
        if new:
            self.status_label.setText(
                f"发现 {len(new)} 期新开奖：{new[0]} … {new[-1]}（共 {info['total']} 期）")
            self.generate()
        else:
            self.status_label.setText(f"已是最新，共 {info['total']} 期")
        self.dataChanged.emit()

    def _on_crawl_failed(self, message: str) -> None:
        self.status_label.setText(f"抓取失败：{message}")


# ---------------------------------------------------------------- 历史数据
class DltDataPage(ScrollArea):
    COLUMNS = [("期号", 92), ("开奖日期", 104), ("星期", 52), ("前区", 168),
               ("后区", 76), ("一等奖", 74), ("单注奖金", 108), ("销售额", 104),
               ("奖池", 110)]

    def __init__(self, store: DltStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dltDataPage")
        self.store = store

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 32)
        self.vbox.setSpacing(12)

        self.vbox.addWidget(TitleLabel("大乐透历史开奖", self.view))
        sub = CaptionLabel("点击表头可排序；数据来自体彩官网公开接口", self.view)
        sub.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(sub)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.kind_combo = ComboBox(self.view)
        self.kind_combo.addItems(["最近 100 期", "最近 300 期", "最近 1000 期", "全部"])
        self.kind_combo.setCurrentIndex(0)
        self.kind_combo.setFixedWidth(140)
        self.kind_combo.currentIndexChanged.connect(self.reload)
        bar.addWidget(self.kind_combo)
        self.info = CaptionLabel("", self.view)
        self.info.setStyleSheet("color:#8A8A8A;")
        bar.addWidget(self.info)
        bar.addStretch(1)
        self.vbox.addLayout(bar)

        self.table = QTableWidget(self.view)
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c for c, _ in self.COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        for i, (_, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)
        header.setStretchLastSection(True)
        self.table.setStyleSheet(
            "QTableWidget{background:#FFFFFF;border:1px solid #E6E6E6;"
            "border-radius:8px;alternate-background-color:#FAFAFA;}"
            "QHeaderView::section{background:#F5F5F5;border:none;"
            "border-bottom:1px solid #E6E6E6;padding:7px 8px;color:#5A5A5A;}")
        font = QApplication.font()
        self.table.setFont(font)
        header.setFont(font)
        self.vbox.addWidget(self.table, 1)
        self.reload()

    def reload(self) -> None:
        limits = [100, 300, 1000, None]
        limit = limits[self.kind_combo.currentIndex()]
        asc = self.store.asc
        rows = list(reversed(asc[-limit:])) if limit else list(reversed(asc))
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            values = [d.issue, d.date, d.week, d.front_text, d.back_text,
                      "-" if d.first_count is None else str(d.first_count),
                      fmt_money(d.first_money), fmt_money(d.sales), fmt_money(d.pool)]
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if c == 3:
                    item.setForeground(QColor(RED))
                elif c == 4:
                    item.setForeground(QColor(BLUE))
                self.table.setItem(r, c, item)
        self.info.setText(f"显示 {len(rows)} / {self.store.count} 期")


# ---------------------------------------------------------------- 走势图
class DltChartPage(ScrollArea):
    SEGMENTS = [("front", "前区频次"), ("back", "后区频次"), ("sum", "和值走势")]

    def __init__(self, store: DltStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dltChartPage")
        self.store = store

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 24)
        self.vbox.setSpacing(10)

        self.vbox.addWidget(TitleLabel("大乐透走势", self.view))
        sub = CaptionLabel("频次偏差属于随机波动，不构成可预测规律", self.view)
        sub.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(sub)

        self.segment = SegmentedWidget(self.view)
        for key, text in self.SEGMENTS:
            self.segment.addItem(key, text)
        self.segment.currentItemChanged.connect(lambda key: self._switch(key))
        self.vbox.addWidget(self.segment)

        card = CardWidget(self.view)
        card.setBorderRadius(10)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(8, 8, 8, 8)
        self.plot = pg.PlotWidget(background="w")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setMouseEnabled(x=False, y=False)
        card_lay.addWidget(self.plot)
        self.vbox.addWidget(card, 1)

        self.caption = CaptionLabel("", self.view)
        self.caption.setStyleSheet("color:#9A9A9A;")
        self.caption.setWordWrap(True)
        self.vbox.addWidget(self.caption)

        self.segment.setCurrentItem("front")
        self._switch("front")

    def select(self, key: str) -> None:
        self.segment.setCurrentItem(key)
        self._switch(key)

    def reload(self) -> None:
        key = self.segment.currentRouteKey() or "front"
        self._switch(key)

    def _switch(self, key: str) -> None:
        try:
            self.plot.clear()
        except RuntimeError:
            return
        if not self.store.available:
            self.caption.setText("还没有数据")
            return
        fs = self.store.features()
        if key == "front":
            nums = list(range(1, FRONT_MAX + 1))
            values = [fs.front_count[n] for n in nums]
            bars = pg.BarGraphItem(x=nums, height=values, width=0.72,
                                   brush=pg.mkBrush(RED))
            self.plot.addItem(bars)
            self.plot.setLabel("left", "出现次数")
            self.plot.setLabel("bottom", "前区号码")
            self.plot.setXRange(0.3, FRONT_MAX + 0.7, padding=0)
            mean = sum(values) / len(values)
            self.plot.addLine(y=mean, pen=pg.mkPen("#8A8A8A", style=Qt.DashLine))
            self.plot.setTitle(f"前区号码出现次数（共 {fs.n} 期）")
            lo = min(nums, key=lambda n: fs.front_count[n])
            hi = max(nums, key=lambda n: fs.front_count[n])
            self.caption.setText(
                f"最多 {hi:02d}（{fs.front_count[hi]} 次），最少 {lo:02d}"
                f"（{fs.front_count[lo]} 次），理论期望 {fs.n * 5 / 35:.1f} 次。")
        elif key == "back":
            nums = list(range(1, BACK_MAX + 1))
            values = [fs.back_count[n] for n in nums]
            bars = pg.BarGraphItem(x=nums, height=values, width=0.62,
                                   brush=pg.mkBrush(BLUE))
            self.plot.addItem(bars)
            self.plot.setLabel("left", "出现次数")
            self.plot.setLabel("bottom", "后区号码")
            self.plot.setXRange(0.3, BACK_MAX + 0.7, padding=0)
            mean = sum(values) / len(values)
            self.plot.addLine(y=mean, pen=pg.mkPen("#8A8A8A", style=Qt.DashLine))
            self.plot.setTitle(f"后区号码出现次数（共 {fs.n} 期）")
            lo = min(nums, key=lambda n: fs.back_count[n])
            hi = max(nums, key=lambda n: fs.back_count[n])
            self.caption.setText(
                f"最多 {hi:02d}（{fs.back_count[hi]} 次），最少 {lo:02d}"
                f"（{fs.back_count[lo]} 次），理论期望 {fs.n * 2 / 12:.1f} 次。")
        else:
            recent = self.store.recent(120)[::-1]
            xs = list(range(len(recent)))
            ys = [sum(d.front) for d in recent]
            self.plot.plot(xs, ys, pen=pg.mkPen(RED, width=2))
            self.plot.setLabel("left", "前区和值")
            self.plot.setLabel("bottom", "最近 120 期")
            self.plot.setTitle("最近 120 期前区和值")
            if ys:
                mean = sum(ys) / len(ys)
                self.plot.addLine(y=mean, pen=pg.mkPen("#8A8A8A", style=Qt.DashLine))
                self.caption.setText(
                    f"最近 120 期和值均值 {mean:.1f}，最低 {min(ys)}，最高 {max(ys)}；"
                    f"全量均值 {fs.mean_sum:.1f}、标准差 {fs.std_sum:.1f}。")
