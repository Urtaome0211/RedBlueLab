# -*- coding: utf-8 -*-
"""号码筛选器：把全部 1,107,568 注红球组合铺开，按条件实时过滤。"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QLineEdit,
                               QVBoxLayout, QWidget)

from qfluentwidgets import (CaptionLabel, CardWidget, FluentIcon as FIF, LineEdit,
                            PrimaryPushButton, PushButton, ScrollArea,
                            StrongBodyLabel, TitleLabel)

from ...core import expand, universal
from ...core.recommend import Ticket
from ...core.store import DataStore
from ..helpers import FilterWorker
from ..widgets import Ball, Divider, TicketCard, muted, number_spin


class FilterPage(ScrollArea):
    dataChanged = Signal()

    def __init__(self, store: DataStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("filterPage")
        self.store = store
        self.worker: FilterWorker | None = None
        self.ready = False
        self.tickets: list[Ticket] = []

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 32)
        self.vbox.setSpacing(14)

        self.vbox.addWidget(TitleLabel("号码筛选器", self.view))
        sub = CaptionLabel(
            "全部 1,107,568 注红球组合已在本地展开，勾选条件后立刻显示还剩多少注。"
            "条件只改变你选的号，不改变中奖概率。", self.view)
        sub.setStyleSheet("color:#8A8A8A;")
        sub.setWordWrap(True)
        self.vbox.addWidget(sub)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_form(), 0)
        body.addLayout(self._build_result(), 1)
        self.vbox.addLayout(body, 1)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(160)
        self.timer.timeout.connect(self.refresh_count)

        self._start_init()

    # ------------------------------------------------ 左侧表单
    def _build_form(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setFixedWidth(440)
        card.setBorderRadius(10)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        lay.addWidget(StrongBodyLabel("红球条件", card))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.sp_sum = self._pair(grid, 0, "和值", 21, 183, 80, 130)
        self.sp_span = self._pair(grid, 1, "跨度", 0, 32, 15, 32)
        self.sp_odd = self._pair(grid, 2, "奇数个数", 0, 6, 2, 4)
        self.sp_big = self._pair(grid, 3, "大号个数(≥17)", 0, 6, 0, 6)
        self.sp_zone = self._pair(grid, 4, "每区个数", 0, 6, 1, 4)
        self.sp_consec = self._pair(grid, 5, "连号对数", 0, 5, 0, 5)
        self.sp_ac = self._pair(grid, 6, "AC 值", -5, 10, -5, 10)
        self.sp_prime = self._pair(grid, 7, "质数个数", 0, 6, 0, 6)
        self.sp_tail = self._pair(grid, 8, "尾数种类", 1, 6, 1, 6)
        self.sp_repeat = self._pair(grid, 9, "与上期重号", 0, 6, 0, 6)
        lay.addLayout(grid)

        lay.addWidget(Divider(card))

        lay.addWidget(muted("必含号码（空格或逗号分隔）", card))
        self.include_edit = LineEdit(card)
        self.include_edit.setPlaceholderText("例如 01 14 22")
        lay.addWidget(self.include_edit)

        lay.addWidget(muted("排除号码", card))
        self.exclude_edit = LineEdit(card)
        self.exclude_edit.setPlaceholderText("例如 21 33")
        lay.addWidget(self.exclude_edit)

        lay.addWidget(Divider(card))

        pick_row = QHBoxLayout()
        pick_row.setSpacing(8)
        pick_row.addWidget(muted("随机取", card))
        self.sample_spin = number_spin(1, 50, 5, 84, parent=card)
        pick_row.addWidget(self.sample_spin)
        pick_row.addWidget(muted("注", card))
        pick_row.addStretch(1)
        self.sample_btn = PrimaryPushButton(FIF.SYNC, "生成号码", card)
        self.sample_btn.clicked.connect(self.sample_tickets)
        pick_row.addWidget(self.sample_btn)
        lay.addLayout(pick_row)

        reset = PushButton(FIF.BROOM, "恢复默认条件", card)
        reset.clicked.connect(self.reset)
        lay.addWidget(reset)
        lay.addStretch(1)

        for widget in (self.include_edit, self.exclude_edit):
            widget.textChanged.connect(self.schedule)
        for pair in self._all_pairs():
            for spin in pair:
                spin.valueChanged.connect(self.schedule)
        return card

    def _pair(self, grid: QGridLayout, row: int, label: str, lo: int, hi: int,
              vlo: int, vhi: int):
        cap = muted(label, self.view)
        cap.setFixedWidth(112)
        grid.addWidget(cap, row, 0, Qt.AlignVCenter)
        box = QHBoxLayout()
        box.setSpacing(6)
        box.setContentsMargins(0, 0, 0, 0)
        a = number_spin(lo, hi, vlo, 78, parent=self.view)
        b = number_spin(lo, hi, vhi, 78, parent=self.view)
        box.addWidget(a)
        box.addWidget(CaptionLabel("~", self.view))
        box.addWidget(b)
        box.addStretch(1)
        host = QWidget(self.view)
        host.setLayout(box)
        host.setFixedHeight(33)
        grid.addWidget(host, row, 1, Qt.AlignVCenter)
        return a, b

    def _all_pairs(self):
        return [self.sp_sum, self.sp_span, self.sp_odd, self.sp_big, self.sp_zone,
                self.sp_consec, self.sp_ac, self.sp_prime, self.sp_tail, self.sp_repeat]

    # ------------------------------------------------ 右侧结果
    def _build_result(self):
        col = QVBoxLayout()
        col.setSpacing(12)

        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(6)
        self.count_label = StrongBodyLabel("准备中…", card)
        self.count_label.setStyleSheet("font-size:30px;color:#C00000;")
        self.hint_label = CaptionLabel("", card)
        self.hint_label.setStyleSheet("color:#8A8A8A;")
        self.rate_label = CaptionLabel("", card)
        self.rate_label.setStyleSheet("color:#8A8A8A;")
        lay.addWidget(self.count_label)
        lay.addWidget(self.hint_label)
        lay.addWidget(self.rate_label)
        lay.addSpacing(4)
        self.cond_label = CaptionLabel("", card)
        self.cond_label.setStyleSheet("color:#8A8A8A;")
        self.cond_label.setWordWrap(True)
        lay.addWidget(self.cond_label)
        col.addWidget(card)

        head = QHBoxLayout()
        self.tickets_title = muted("按当前条件随机生成的号码", self.view)
        self.tickets_title.setWordWrap(True)
        head.addWidget(self.tickets_title)
        head.addStretch(1)
        self.copy_btn = PushButton(FIF.COPY, "复制", self.view)
        self.copy_btn.clicked.connect(self.copy_tickets)
        self.copy_btn.setEnabled(False)
        head.addWidget(self.copy_btn)
        col.addLayout(head)

        host = QWidget(self.view)
        self.tickets_layout = QVBoxLayout(host)
        self.tickets_layout.setContentsMargins(0, 0, 0, 0)
        self.tickets_layout.setSpacing(8)
        col.addWidget(host)
        col.addStretch(1)
        return col

    # ------------------------------------------------ 初始化 / 计算
    def _start_init(self) -> None:
        self._set_enabled(False)
        self.worker = FilterWorker(self)
        self.worker.message.connect(self.count_label.setText)
        self.worker.ready.connect(self._on_ready)
        self.worker.failed.connect(lambda m: self.count_label.setText(f"初始化失败：{m}"))
        self.worker.start()

    def _on_ready(self) -> None:
        self.ready = True
        self._set_enabled(True)
        self.refresh_count()

    def _set_enabled(self, enabled: bool) -> None:
        widgets = [self.include_edit, self.exclude_edit, self.sample_spin,
                   self.sample_btn]
        for pair in self._all_pairs():
            widgets.extend(pair)
        for widget in widgets:
            widget.setEnabled(enabled)

    def _spec(self) -> universal.FilterSpec:
        def rng(pair):
            a, b = int(pair[0].value()), int(pair[1].value())
            return (min(a, b), max(a, b))

        return universal.FilterSpec(
            sum=rng(self.sp_sum), span=rng(self.sp_span), odd=rng(self.sp_odd),
            big=rng(self.sp_big), zone=rng(self.sp_zone), consec=rng(self.sp_consec),
            ac=rng(self.sp_ac), prime=rng(self.sp_prime), tail=rng(self.sp_tail),
            repeat=rng(self.sp_repeat),
            include=tuple(expand.parse_numbers(self.include_edit.text())),
            exclude=tuple(expand.parse_numbers(self.exclude_edit.text())),
        ).normalized()

    def schedule(self) -> None:
        if self.ready:
            self.timer.start()

    def _prev_reds(self) -> list[int]:
        draw = self.store.latest()
        return list(draw.reds) if draw else []

    def refresh_count(self) -> None:
        if not self.ready:
            return
        spec = self._spec()
        t0 = time.perf_counter()
        n = universal.count(spec, self._prev_reds())
        ms = (time.perf_counter() - t0) * 1000
        total = universal.TOTAL_COMBOS
        self.count_label.setText(f"{n:,} 注")
        self.hint_label.setText(
            f"占全部 {total:,} 注的 {n / total:.2%} · 过滤耗时 {ms:.0f} ms"
            if n else "没有符合条件的组合，放宽一些条件试试")
        self.rate_label.setText(
            f"按这个条件，每 {total / n:.0f} 注里大约有 1 注符合（本身不提高中奖概率）"
            if n else "")
        self.cond_label.setText("条件：" + universal.combinations_text(spec))

    # ------------------------------------------------ 出号
    def sample_tickets(self) -> None:
        if not self.ready:
            return
        spec = self._spec()
        n = self.sample_spin.value()
        rows = universal.sample(spec, n, self._prev_reds())
        if not rows:
            self.count_label.setText("没有符合条件的组合")
            return
        self.tickets = [Ticket(tuple(int(x) for x in reds), 1) for reds in rows]
        while self.tickets_layout.count():
            item = self.tickets_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, ticket in enumerate(self.tickets, 1):
            self.tickets_layout.addWidget(TicketCard(ticket, i, show_score=False,
                                                     show_blue=False, parent=self.view))
        self.copy_btn.setEnabled(True)
        self.tickets_title.setText(
            f"按当前条件随机生成 {len(self.tickets)} 注红球（蓝球自己选 1–16）")

    def copy_tickets(self) -> None:
        if not self.tickets:
            return
        text = "\n".join(
            " ".join(f"{n:02d}" for n in t.reds) for t in self.tickets)
        QApplication.clipboard().setText(text)
        self.count_label.setText(f"已复制 {len(self.tickets)} 注号码")

    def reset(self) -> None:
        defaults = {
            self.sp_sum: (80, 130), self.sp_span: (15, 32), self.sp_odd: (2, 4),
            self.sp_big: (0, 6), self.sp_zone: (1, 4), self.sp_consec: (0, 5),
            self.sp_ac: (-5, 10), self.sp_prime: (0, 6), self.sp_tail: (1, 6),
            self.sp_repeat: (0, 6),
        }
        for pair, (lo, hi) in defaults.items():
            pair[0].blockSignals(True)
            pair[1].blockSignals(True)
            pair[0].setValue(lo)
            pair[1].setValue(hi)
            pair[0].blockSignals(False)
            pair[1].blockSignals(False)
        self.include_edit.clear()
        self.exclude_edit.clear()
        self.refresh_count()
