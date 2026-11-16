# -*- coding: utf-8 -*-
"""推荐页：最新开奖 + 参数 + 推荐注卡 + 抓取按钮。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, CheckBox, ComboBox,
                            FluentIcon as FIF, PrimaryPushButton, PushButton,
                            ScrollArea, StrongBodyLabel, TitleLabel)

from ... import paths
from ...core import ledger as ledger_mod
from ...core import recommend as rec
from ...core.recommend import RecParams, Ticket
from ...core.store import DataStore, Draw
from ..helpers import CrawlWorker, RecommendWorker, fmt_money
from ..widgets import Ball, BallLine, Divider, TicketCard, muted, number_spin

KINDS = [("stats", "统计打分"), ("random", "约束随机"), ("coverage", "覆盖优化")]


def _vsep() -> QWidget:
    w = QWidget()
    w.setFixedWidth(1)
    w.setStyleSheet("background: rgba(128,128,128,0.18);")
    return w


class LatestCard(CardWidget):
    """最新一期开奖 + 数据状态。"""

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
            self.pool.setText("-")
            self.sales.setText("-")
            self.first.setText("-")
            return

        self.issue_label.setText(f"{draw.issue} 期")
        self.date_label.setText(f"{draw.date}  周{draw.week}")
        for n in draw.reds:
            self.balls_layout.addWidget(Ball(n, "red", 36, self.balls_host))
        plus = BodyLabel("+", self.balls_host)
        plus.setStyleSheet("color:#8A8A8A;font-weight:600;")
        self.balls_layout.addWidget(plus)
        self.balls_layout.addWidget(Ball(draw.blue, "blue", 36, self.balls_host))

        self.pool.setText(fmt_money(draw.pool))
        self.sales.setText(fmt_money(draw.sales))
        if draw.first_count is None:
            self.first.setText("-")
        elif draw.first_count == 0:
            self.first.setText("空开")
        else:
            self.first.setText(f"{draw.first_count} 注 / {fmt_money(draw.first_money)}")


class RecommendPage(ScrollArea):
    dataChanged = Signal()
    recorded = Signal()

    def __init__(self, store: DataStore, params: RecParams,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("recommendPage")
        self.store = store
        self.params = params
        self.worker: CrawlWorker | None = None
        self.gen_worker: RecommendWorker | None = None
        self.tickets: list[Ticket] = []
        self.last_info: dict = {}
        self.ledger = ledger_mod.Ledger()

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 32)
        self.vbox.setSpacing(14)

        title = TitleLabel("号码推荐", self.view)
        subtitle = CaptionLabel("基于历史开奖的统计组合 · 仅供娱乐参考，不能提高中奖概率", self.view)
        subtitle.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(title)
        self.vbox.addWidget(subtitle)

        self.latest_card = LatestCard(self.view)
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
        self._sync_kind()

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
        index = next((i for i, (k, _) in enumerate(KINDS) if k == self.params.kind), 0)
        self.kind_combo.setCurrentIndex(index)
        self.kind_combo.setFixedWidth(140)
        self.kind_combo.currentIndexChanged.connect(self._sync_kind)
        algo_box.addWidget(self.kind_combo)
        lay.addLayout(algo_box)

        count_box = QVBoxLayout()
        count_box.setSpacing(4)
        count_box.addWidget(muted("注数", card))
        self.count_spin = number_spin(1, 20, self.params.n_tickets, 92, parent=card)
        count_box.addWidget(self.count_spin)
        lay.addLayout(count_box)

        pool_box = QVBoxLayout()
        pool_box.setSpacing(4)
        pool_box.addWidget(muted("号码池", card))
        self.pool_spin = number_spin(12, 20, 18, 92, parent=card)
        self.pool_spin.setToolTip("覆盖优化专用：池子越小保底越高，越大越分散")
        pool_box.addWidget(self.pool_spin)
        lay.addLayout(pool_box)

        self.record_check = CheckBox("记入成绩单", card)
        self.record_check.setChecked(True)
        lay.addWidget(self.record_check)

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
            self.footer.setText("还没有数据：点击「抓取新开奖」从官网拉取全部历史开奖。")
            return
        ev = rec.expected_value(self.store)
        summary = self.store.summary()
        self.footer.setText(
            f"数据：{summary['count']} 期（{summary['first']} ~ {summary['last']}）· "
            f"更新于 {summary['updated']}　|　"
            f"每注 2 元，按历史奖金均值估算单注期望回报约 {ev['ev_per_ticket']:.2f} 元"
            f"（返还率 {ev['return_rate']:.1%}）。中奖号码独立随机，任何选号方法都不改变概率。"
        )

    # ------------------------------------------------ 生成
    def _sync_kind(self) -> None:
        kind = KINDS[self.kind_combo.currentIndex()][0]
        is_cov = kind == "coverage"
        self.pool_spin.setEnabled(is_cov)
        if is_cov:
            self.count_spin.setMaximum(12)
            self.count_spin.setValue(min(self.count_spin.value(), 12))
            self.record_check.setChecked(True)
        else:
            self.count_spin.setMaximum(20)
        self.status_label.setText(
            "覆盖优化：把注数铺开在号码池上，池内 6 个全中时保证最差也能中几红（池子越小保底越高）"
            if is_cov else "就绪")

    def generate(self, auto: bool = False) -> None:
        """auto=True 表示启动时自动展示，不写成绩单。"""
        if not self.store.available:
            self.status_label.setText("没有历史数据，请先抓取开奖数据")
            return
        if self.gen_worker and self.gen_worker.isRunning():
            return

        self.params.kind = KINDS[self.kind_combo.currentIndex()][0]
        self.params.n_tickets = self.count_spin.value()
        kind = self.params.kind
        self.params.validate()

        self.status_label.setText("生成中…")
        self.generate_btn.setEnabled(False)
        self.gen_worker = RecommendWorker(self.store, kind, self.params,
                                          self.pool_spin.value(), self)
        self.gen_worker.done.connect(lambda t, i: self._on_generated(t, i, kind, auto))
        self.gen_worker.failed.connect(self._on_generate_failed)
        self.gen_worker.finished.connect(lambda: self.generate_btn.setEnabled(True))
        self.gen_worker.start()

    def _on_generated(self, tickets: list[Ticket], info: dict, kind: str,
                      auto: bool = False) -> None:
        self.tickets = tickets
        self.last_info = info or {}
        self._render_tickets(kind)

        text = f"{rec.describe_params(self.params, kind)} · 已生成 {len(tickets)} 注"
        if info:
            pool_text = " ".join(f"{n:02d}" for n in info.get("pool", []))
            text += (f" · 号码池 {len(info.get('pool', []))} 个：{pool_text}"
                     f" · 池内全中时保底 {info.get('floor')} 红、平均 {info.get('avg_hit', 0):.1f} 红")

        if self.record_check.isChecked() and not auto:
            record = self.ledger.add_batch(self.store, tickets, kind, self.params)
            if record:
                text += f" · 已记入成绩单（共 {len(self.ledger.records)} 批）"
                self.recorded.emit()
            else:
                text += " · 与上次推荐相同，未重复记录"
        self.status_label.setText(text)

    def _on_generate_failed(self, message: str) -> None:
        self.status_label.setText(f"生成失败：{message}")

    def _render_tickets(self, kind: str) -> None:
        while self.tickets_layout.count():
            item = self.tickets_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, t in enumerate(self.tickets, 1):
            self.tickets_layout.addWidget(
                TicketCard(t, i, show_score=False, parent=self.view))

    # ------------------------------------------------ 抓取
    def start_crawl(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self._set_busy(True)
        self.status_label.setText("正在抓取官网数据…")
        self.worker = CrawlWorker(self.store, self)
        self.worker.message.connect(self.status_label.setText)
        self.worker.succeeded.connect(self._on_crawl_done)
        self.worker.failed.connect(self._on_crawl_failed)
        self.worker.finished.connect(lambda: self._set_busy(False))
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.crawl_btn.setEnabled(not busy)
        self.generate_btn.setEnabled(not busy)
        self.crawl_btn.setText("抓取中…" if busy else "抓取新开奖")

    def _on_crawl_done(self, info: dict) -> None:
        self.store.load(force=True)
        self.refresh_latest()
        self._update_footer()
        new: list[str] = info.get("new") or []
        if new:
            self.status_label.setText(
                f"发现 {len(new)} 期新开奖：{new[0]} … {new[-1]}（共 {info['total']} 期）")
            self.generate()
        else:
            self.status_label.setText(f"已是最新，共 {info['total']} 期")
        self.dataChanged.emit()

    def _on_crawl_failed(self, message: str) -> None:
        self.status_label.setText(f"抓取失败：{message}")
        self.dataChanged.emit()

