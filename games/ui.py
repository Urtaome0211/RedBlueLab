"""通用界面：为每个彩种生成「推荐」「历史数据」两个页面。"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSizePolicy, QTableView, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, CheckBox, ComboBox, PrimaryPushButton,
    PushButton, ScrollArea, SearchLineEdit, SegmentedWidget, StrongBodyLabel, SubtitleLabel,
    TableView, setFont, InfoBar, InfoBarPosition, FluentIcon as FIF,
)

from ssq.ui.widgets import Divider, muted, number_spin

from . import build as B
from . import fetch as F
from . import recommend as R
from . import spec as S
from .store import GameStore

RED = "#E1251B"
BLUE = "#1F6FD0"


def fmt_money(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    value = float(value)
    if value >= 1e8:
        return f"{value / 1e8:.2f} 亿"
    if value >= 1e4:
        return f"{value / 1e4:.0f} 万"
    return f"{value:,.0f}"


class NumberBoard(QWidget):
    """一注号码的可视化：每个 zone 一行球。"""

    def __init__(self, groups: list[list[int]], spec: S.GameSpec, size: int = 30,
                 per_row: int = 10, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        zones = [(z, n) for z, n in zip(spec.zones, groups) if n]
        # 位数型（3D / 排列3 / 排列5 / 7星彩）各 zone 只有 1 个数，拼成一行更好看
        one_row = bool(zones) and (all(z.count == 1 for z, _ in zones)
                                   or all(z.ordered for z, _ in zones))
        if one_row:
            row = QWidget(self)
            flow = QHBoxLayout(row)
            flow.setContentsMargins(0, 0, 0, 0)
            flow.setSpacing(4)
            for idx, (zone, nums) in enumerate(zones):
                color = RED if idx == 0 else BLUE
                for n in nums:
                    ball = QLabel(str(n), row)
                    ball.setAlignment(Qt.AlignCenter)
                    ball.setFixedSize(size, size)
                    ball.setStyleSheet(
                        f"background:{color};color:white;border-radius:{size // 2}px;"
                        f"font-size:{max(10, size // 3)}px;font-weight:600;")
                    flow.addWidget(ball)
            flow.addStretch(1)
            lay.addWidget(row)
            return
        for zone, nums in zones:
            color = RED if zone is spec.zones[0] else BLUE
            # 一行放不下就换行（快乐8 一期 20 个号）
            for start in range(0, len(nums), per_row):
                row = QWidget(self)
                flow = QHBoxLayout(row)
                flow.setContentsMargins(0, 0, 0, 0)
                flow.setSpacing(4)
                for n in nums[start:start + per_row]:
                    ball = QLabel(f"{n:0{zone.width}d}" if zone.width == 2 else str(n), row)
                    ball.setAlignment(Qt.AlignCenter)
                    ball.setFixedSize(size, size)
                    ball.setStyleSheet(
                        f"background:{color};color:white;border-radius:{size // 2}px;"
                        f"font-size:{max(10, size // 3)}px;font-weight:600;")
                    flow.addWidget(ball)
                flow.addStretch(1)
                lay.addWidget(row)


class TicketCard(CardWidget):
    def __init__(self, index: int, ticket: R.Ticket, spec: S.GameSpec, parent=None):
        super().__init__(parent)
        self.setBorderRadius(10)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(14)

        no = StrongBodyLabel(f"{index:02d}", self)
        no.setFixedWidth(28)
        lay.addWidget(no, 0, Qt.AlignVCenter)
        per_row = max(5, min(10, max((len(g) for g in ticket.groups), default=5)))
        lay.addWidget(NumberBoard(ticket.groups, spec, 30, per_row=per_row), 1,
                      Qt.AlignVCenter)

        right = QVBoxLayout()
        right.setSpacing(2)
        info = CaptionLabel(ticket.composition(spec), self)
        info.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
        right.addWidget(info)
        if ticket.reason and ticket.reason.strip() != ticket.composition(spec).strip():
            reason = CaptionLabel(ticket.reason, self)
            reason.setTextColor(QColor("#A0A0A0"), QColor("#8A8A8A"))
            right.addWidget(reason)
        lay.addLayout(right, 0)

        self.copy_btn = PushButton(FIF.COPY, "复制", self)
        self.copy_btn.setFixedWidth(74)
        self.copy_btn.clicked.connect(lambda: self._copy(ticket, spec))
        lay.addWidget(self.copy_btn, 0, Qt.AlignVCenter)

    def _copy(self, ticket: R.Ticket, spec: S.GameSpec) -> None:
        QGuiApplication.clipboard().setText(ticket.text(spec))
        self.copy_btn.setText("已复制")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("复制"))


class CrawlWorker(QThread):
    message = Signal(str)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, game: S.GameSpec, parent=None):
        super().__init__(parent)
        self.game = game
        self.new = 0

    def run(self) -> None:                       # noqa: D401
        try:
            before = GameStore(self.game.key).count
            meta = F.crawl(self.game, log=self.message.emit)
            B.build(self.game, log=self.message.emit)
            after = GameStore(self.game.key).count
            self.done.emit({"total": meta.get("total", after), "new": after - before})
        except Exception as exc:                 # noqa: BLE001
            self.failed.emit(str(exc))


class LatestCard(CardWidget):
    def __init__(self, store: GameStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setBorderRadius(12)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(22)

        left = QVBoxLayout()
        left.setSpacing(2)
        self.issue_label = StrongBodyLabel("-", self)
        setFont(self.issue_label, 26)
        self.date_label = CaptionLabel("-", self)
        self.date_label.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
        left.addWidget(self.issue_label)
        left.addWidget(self.date_label)
        lay.addLayout(left, 0)

        self.board = NumberBoard([], store.spec, 28, per_row=10)
        lay.addWidget(self.board, 1)

        self.stats = []
        for name in ("销售额", "奖池"):
            box = QVBoxLayout()
            box.setSpacing(0)
            value = StrongBodyLabel("-", self)
            setFont(value, 15)
            cap = CaptionLabel(name, self)
            cap.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
            box.addWidget(value, 0, Qt.AlignRight)
            box.addWidget(cap, 0, Qt.AlignRight)
            lay.addLayout(box, 0)
            self.stats.append(value)
        self.refresh()

    def refresh(self) -> None:
        draw = self.store.latest()
        if draw is None:
            return
        self.issue_label.setText(f"{draw.issue} 期")
        self.date_label.setText(f"{draw.date} {('周' + draw.week) if draw.week else ''}".strip())
        Lay = self.board.layout()
        while Lay.count():
            item = Lay.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        Lay.addWidget(NumberBoard(draw.groups, self.store.spec, 28, per_row=10))
        self.stats[0].setText(fmt_money(draw.sales))
        # 排列3/福彩3D 这类没有奖池概念的彩种，接口给 0，显示成「-」
        self.stats[1].setText(fmt_money(draw.pool) if draw.pool else "-")


class RecommendPage(ScrollArea):
    dataChanged = Signal()

    def __init__(self, store: GameStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.spec = store.spec
        self.params = R.RecParams()
        self.last_info: dict = {}
        self.worker: CrawlWorker | None = None
        self.setObjectName(f"{self.spec.key}Page")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 36)
        self.vbox.setSpacing(16)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet("#view{background:transparent;}")

        self.title = SubtitleLabel(f"{self.spec.name}推荐", self)
        self.vbox.addWidget(self.title)
        subtitle = CaptionLabel(
            f"{self.spec.summary}　仅供参考，不能提高中奖概率", self)
        subtitle.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
        self.vbox.addWidget(subtitle)

        self.latest_card = LatestCard(store, self)
        self.vbox.addWidget(self.latest_card)

        self.control = CardWidget(self)
        self.control.setBorderRadius(12)
        row = QHBoxLayout(self.control)
        row.setContentsMargins(22, 14, 22, 14)
        row.setSpacing(18)

        row.addWidget(CaptionLabel("算法", self.control))
        self.kind_combo = ComboBox(self.control)
        self.kind_combo.addItems(["统计打分", "约束随机"])
        self.kind_combo.setFixedWidth(112)
        row.addWidget(self.kind_combo)

        row.addWidget(CaptionLabel("注数", self.control))
        self.count_spin = number_spin(1, 20, self.params.n_tickets, 84, parent=self.control)
        row.addWidget(self.count_spin)

        row.addWidget(CaptionLabel("和值", self.control))
        lo, hi = R._default_range(store)
        self.sum_lo = number_spin(0, 2000, max(0, lo), 80, parent=self.control)
        self.sum_hi = number_spin(0, 3000, max(1, hi), 80, parent=self.control)
        row.addWidget(self.sum_lo)
        row.addWidget(CaptionLabel("~", self.control))
        row.addWidget(self.sum_hi)
        row.addStretch(1)

        self.gen_btn = PrimaryPushButton(FIF.SYNC, "生成推荐", self.control)
        self.gen_btn.clicked.connect(self.generate)
        row.addWidget(self.gen_btn)

        self.crawl_btn = PushButton(FIF.DOWNLOAD, "抓取新开奖", self.control)
        self.crawl_btn.clicked.connect(self.start_crawl)
        row.addWidget(self.crawl_btn)
        self.vbox.addWidget(self.control)

        self.status = CaptionLabel("", self)
        self.status.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
        self.vbox.addWidget(self.status)

        self.tickets_box = QVBoxLayout()
        self.tickets_box.setSpacing(10)
        holder = QWidget(self)
        holder.setLayout(self.tickets_box)
        self.vbox.addWidget(holder)
        self.vbox.addStretch(1)

        if self.store.available():
            self.generate()
        else:
            self.status.setText("还没有数据，点右侧「抓取新开奖」开始")

    # ---------------------------------------------------------------- 生成
    def generate(self) -> None:
        if not self.store.available():
            return
        self.store.load(force=True)
        self.latest_card.refresh()
        kind = "stats" if self.kind_combo.currentIndex() == 0 else "random"
        params = R.RecParams(n_tickets=self.count_spin.value(),
                             sum_lo=self.sum_lo.value(), sum_hi=self.sum_hi.value(),
                             kind=kind, seed=int(time.time() * 1000) % 100000)
        try:
            tickets = R.recommend(self.store, kind=kind, params=params)
            ev = R.expected_value(self.store)
        except Exception as exc:                 # noqa: BLE001
            InfoBar.error("生成失败", str(exc), parent=self)
            return
        self.last_info = {"ev": ev, "tickets": tickets, "kind": kind}
        self._render(tickets)
        self.status.setText(
            f"{R.describe_params(params, kind)} · 单注期望 {ev['ev_per_ticket']:.3f} 元"
            f"（返还率 {ev['return_rate'] * 100:.1f}%）")

    def _render(self, tickets: list[R.Ticket]) -> None:
        while self.tickets_box.count():
            item = self.tickets_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)      # 立刻退场，避免旧卡片残影
                widget.deleteLater()
        for i, ticket in enumerate(tickets, 1):
            self.tickets_box.addWidget(TicketCard(i, ticket, self.spec))

    # ---------------------------------------------------------------- 抓取
    def start_crawl(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.crawl_btn.setEnabled(False)
        self.status.setText(f"正在抓取{self.spec.name}…")
        self.worker = CrawlWorker(self.spec, self)
        self.worker.message.connect(self.status.setText)
        self.worker.done.connect(self._on_crawl_done)
        self.worker.failed.connect(self._on_crawl_failed)
        self.worker.start()

    def _on_crawl_done(self, info: dict) -> None:
        self.crawl_btn.setEnabled(True)
        new = info.get("new", 0)
        self.status.setText(
            f"已是最新，共 {info.get('total', self.store.count)} 期"
            if not new else f"新增 {new} 期，共 {info.get('total')} 期")
        self.store.load(force=True)
        self.latest_card.refresh()
        self.generate()
        self.dataChanged.emit()

    def _on_crawl_failed(self, message: str) -> None:
        self.crawl_btn.setEnabled(True)
        self.status.setText("抓取失败")

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(5000)


# ---------------------------------------------------------------- 历史数据
class TableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, spec: S.GameSpec, parent=None):
        super().__init__(parent)
        self.df = df
        self.spec = spec
        self.columns = [c for c in df.columns if c not in ("详情链接",)]
        if "星期" in self.columns:
            self.columns.remove("星期")
        # 号码很多时（快乐8 一期 20 个）只留合并列，否则表格挤成一条缝
        if any(z.count > 10 for z in spec.zones):
            numbered = {f"{z.label}{i}" for z in spec.zones for i in range(1, z.count + 1)}
            self.columns = [c for c in self.columns if c not in numbered]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self.columns[index.column()]
        value = self.df.iloc[index.row()][col]
        if role == Qt.DisplayRole:
            if pd.isna(value):
                return "-"
            if isinstance(value, (int, float)) and col.endswith("(元)"):
                return f"{float(value):,.0f}"
            return str(value)
        if role == Qt.TextAlignmentRole and isinstance(value, (int, float)):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section]
        return str(self.df.iloc[section]["期号"])


class DataPage(ScrollArea):
    def __init__(self, store: GameStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.spec = store.spec
        self.setObjectName(f"{self.spec.key}DataPage")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        vbox = QVBoxLayout(self.view)
        vbox.setContentsMargins(36, 28, 36, 36)
        vbox.setSpacing(14)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet("#view{background:transparent;}")

        title = SubtitleLabel(f"{self.spec.name}历史开奖", self)
        vbox.addWidget(title)
        sub = CaptionLabel("双击一行在浏览器打开官网详情", self)
        sub.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
        vbox.addWidget(sub)

        bar = QWidget(self)
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(12)
        self.search = SearchLineEdit(bar)
        self.search.setPlaceholderText("搜索期号，如 2026 或 26")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.reload)
        bar_row.addWidget(self.search)
        self.range_combo = ComboBox(bar)
        self.range_combo.addItems(["最近 50 期", "最近 100 期", "最近 300 期", "全部"])
        self.range_combo.setCurrentIndex(1)
        self.range_combo.setFixedWidth(120)
        self.range_combo.currentIndexChanged.connect(self.reload)
        bar_row.addWidget(self.range_combo)
        bar_row.addStretch(1)
        self.count_label = CaptionLabel("", bar)
        self.count_label.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
        bar_row.addWidget(self.count_label)
        vbox.addWidget(bar)

        self.table = TableView(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(520)
        vbox.addWidget(self.table, 1)

        self.stats = CaptionLabel("", self)
        self.stats.setWordWrap(True)
        self.stats.setTextColor(QColor("#8A8A8A"), QColor("#9A9A9A"))
        vbox.addWidget(self.stats)
        self.reload()

    def reload(self) -> None:
        if not self.store.available():
            return
        df = self.store.load()
        text = self.search.text().strip()
        if text:
            df = df[df["期号"].astype(str).str.contains(text, na=False)]
        limit = {0: 50, 1: 100, 2: 300}.get(self.range_combo.currentIndex())
        if limit:
            df = df.head(limit)
        model = TableModel(df.reset_index(drop=True), self.spec, self)
        self.table.setModel(model)
        self.count_label.setText(f"显示 {len(df)} / {self.store.count} 期")
        for i, name in enumerate(model.columns):
            self.table.setColumnWidth(i, self._col_width(name))
        self.table.horizontalHeader().setStretchLastSection(True)
        self._update_stats()

    def _col_width(self, name: str) -> int:
        if name == "期号":
            return 92
        if name == "开奖日期":
            return 110
        if name.endswith("(元)"):
            return 118
        if name in ("和值", "跨度", "形态"):
            return 74
        if "," in name or name in [z.label for z in self.spec.zones]:
            count = max(z.count for z in self.spec.zones if z.label == name)
            return min(420, 24 + count * 22) if count > 10 else 96 + count * 18
        return 84

    def _update_stats(self) -> None:
        store = self.store
        fs = store.features()
        top = sorted(fs.counts[0].items(), key=lambda kv: -kv[1])[:3]
        low = sorted(fs.counts[0].items(), key=lambda kv: kv[1])[:3]
        zone = self.spec.zones[0]
        width = zone.width
        self.stats.setText(
            f"热号 " + "、".join(f"{n:0{width}d}({c})" for n, c in top)
            + "　|　冷号 " + "、".join(f"{n:0{width}d}({c})" for n, c in low)
            + f"　|　共 {store.count} 期")


def create_pages(key: str) -> tuple[RecommendPage, DataPage]:
    store = GameStore(key)
    return RecommendPage(store), DataPage(store)
