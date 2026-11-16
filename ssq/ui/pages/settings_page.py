# -*- coding: utf-8 -*-
"""设置页：推荐参数、数据集维护、关于。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QPlainTextEdit, QSpinBox, QVBoxLayout,
                               QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, ComboBox,
                            FluentIcon as FIF, PushButton, ScrollArea, Slider,
                            StrongBodyLabel, TitleLabel)

from ... import __version__, paths
from ...config import save_params
from ...core import build
from ...core.recommend import RecParams
from ...core.store import DataStore
from ..helpers import RebuildWorker
from ..widgets import Divider, muted, number_spin

BLUE_MODES = [("balanced", "冷热均衡"), ("hot", "偏热号"), ("cold", "偏冷号"), ("random", "纯随机")]


class SettingsPage(ScrollArea):
    paramsChanged = Signal()
    dataChanged = Signal()

    def __init__(self, store: DataStore, params: RecParams,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.store = store
        self.params = params
        self.rebuild_worker: RebuildWorker | None = None
        self._spins: dict[str, QSpinBox] = {}

        self.view = QWidget()
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(36, 28, 36, 32)
        self.vbox.setSpacing(14)

        self.vbox.addWidget(TitleLabel("设置", self.view))
        hint = CaptionLabel("参数只影响生成偏好与去重规则，不改变中奖概率。", self.view)
        hint.setStyleSheet("color:#8A8A8A;")
        self.vbox.addWidget(hint)

        self.vbox.addWidget(self._build_params_card())
        self.vbox.addWidget(self._build_data_card())
        self.vbox.addWidget(self._build_about_card())
        self.vbox.addStretch(1)

    # ------------------------------------------------ 参数卡
    def _build_params_card(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(StrongBodyLabel("推荐参数", card))

        # 冷热倾向
        lay.addWidget(muted("冷热倾向", card))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.bias_slider = Slider(Qt.Horizontal, card)
        self.bias_slider.setRange(0, 100)
        self.bias_slider.setValue(int(round(self.params.hot_bias * 100)))
        self.bias_slider.valueChanged.connect(self._on_bias)
        self.bias_label = CaptionLabel(self._bias_text(self.params.hot_bias), card)
        self.bias_label.setFixedWidth(150)
        self.bias_label.setStyleSheet("color:#8A8A8A;")
        row.addWidget(self.bias_slider, 1)
        row.addWidget(self.bias_label)
        lay.addLayout(row)

        lay.addWidget(Divider(card))

        # 和值 / 奇偶
        grid = QHBoxLayout()
        grid.setSpacing(28)
        grid.addLayout(self._pair_row("和值范围", "sum_lo", "sum_hi", 21, 183))
        grid.addLayout(self._pair_row("奇偶比（奇）", "odd_min", "odd_max", 0, 6))
        grid.addLayout(self._pair_row("三区个数", "zone_min", "zone_max", 0, 6))
        grid.addStretch(1)
        lay.addLayout(grid)

        lay.addWidget(Divider(card))

        row2 = QHBoxLayout()
        row2.setSpacing(24)
        row2.addLayout(self._single_row("注间红球重合上限", "max_overlap", 0, 5, " 个"))
        row2.addLayout(self._single_row("允许连号组数", "max_consecutive", 0, 3, " 组"))
        row2.addLayout(self._single_row("最小跨度", "min_span", 0, 32, ""))

        blue_box = QVBoxLayout()
        blue_box.setSpacing(4)
        blue_box.addWidget(muted("蓝球策略", card))
        self.blue_combo = ComboBox(card)
        self.blue_combo.addItems([label for _, label in BLUE_MODES])
        idx = next((i for i, (k, _) in enumerate(BLUE_MODES) if k == self.params.blue_mode), 0)
        self.blue_combo.setCurrentIndex(idx)
        self.blue_combo.setFixedWidth(120)
        self.blue_combo.currentIndexChanged.connect(self._on_blue)
        blue_box.addWidget(self.blue_combo)
        row2.addLayout(blue_box)

        row2.addStretch(1)
        reset_btn = PushButton(FIF.SYNC, "恢复默认", card)
        reset_btn.clicked.connect(self._reset)
        row2.addWidget(reset_btn)
        lay.addLayout(row2)
        return card

    def _pair_row(self, title: str, lo_key: str, hi_key: str, minimum: int,
                  maximum: int) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(muted(title, self.view))
        row = QHBoxLayout()
        row.setSpacing(6)
        lo = number_spin(minimum, maximum, int(getattr(self.params, lo_key)), 78,
                         parent=self.view)
        hi = number_spin(minimum, maximum, int(getattr(self.params, hi_key)), 78,
                         parent=self.view)
        lo.valueChanged.connect(lambda v, k=lo_key: self._on_param(k, v))
        hi.valueChanged.connect(lambda v, k=hi_key: self._on_param(k, v))
        self._spins[lo_key] = lo
        self._spins[hi_key] = hi
        row.addWidget(lo)
        row.addWidget(BodyLabel("~", self.view))
        row.addWidget(hi)
        box.addLayout(row)
        return box

    def _single_row(self, title: str, key: str, minimum: int, maximum: int,
                    suffix: str) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(muted(title, self.view))
        spin = number_spin(minimum, maximum, int(getattr(self.params, key)), 92,
                           suffix=suffix, parent=self.view)
        spin.valueChanged.connect(lambda v, k=key: self._on_param(k, v))
        self._spins[key] = spin
        box.addWidget(spin)
        return box

    # ------------------------------------------------ 数据卡
    def _build_data_card(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("数据集", card))

        self.data_label = CaptionLabel("", card)
        self.data_label.setStyleSheet("color:#8A8A8A;")
        self.data_label.setWordWrap(True)
        lay.addWidget(self.data_label)

        self.path_label = CaptionLabel("", card)
        self.path_label.setStyleSheet("color:#9A9A9A;")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.path_label)

        row = QHBoxLayout()
        row.setSpacing(10)
        open_btn = PushButton(FIF.FOLDER, "打开数据目录", card)
        open_btn.clicked.connect(self._open_folder)
        row.addWidget(open_btn)

        self.rebuild_btn = PushButton(FIF.SYNC, "重建数据集", card)
        self.rebuild_btn.clicked.connect(self._rebuild)
        row.addWidget(self.rebuild_btn)

        self.verify_btn = PushButton(FIF.ACCEPT, "运行校验", card)
        self.verify_btn.clicked.connect(self._verify)
        row.addWidget(self.verify_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.report_view = QPlainTextEdit(card)
        self.report_view.setReadOnly(True)
        self.report_view.setFixedHeight(0)
        self.report_view.setStyleSheet(
            "QPlainTextEdit{background:rgba(128,128,128,0.06);border:none;"
            "border-radius:6px;padding:6px;font-family:Consolas,monospace;font-size:12px;}")
        lay.addWidget(self.report_view)

        self.refresh_info()
        return card

    def _build_about_card(self) -> CardWidget:
        card = CardWidget(self.view)
        card.setBorderRadius(10)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(6)
        lay.addWidget(StrongBodyLabel("关于", card))
        text = (
            f"RedBlue Lab v{__version__}　双色球 + 超级大乐透分析助手\n"
            "数据来源：中国福利彩票发行管理中心（2013 年至今）、中国体育彩票官网（2007 年至今）公开接口。\n"
            "本软件仅做历史数据统计与组合生成，彩票开奖为独立随机事件，"
            "任何选号方法都不能提高中奖概率。请理性购彩、量力而行。"
        )
        label = CaptionLabel(text, card)
        label.setStyleSheet("color:#8A8A8A;")
        label.setWordWrap(True)
        lay.addWidget(label)
        return card

    # ------------------------------------------------ 交互
    @staticmethod
    def _bias_text(value: float) -> str:
        if value >= 0.82:
            return "偏热号（追热）"
        if value >= 0.58:
            return "略偏热号"
        if value > 0.42:
            return "均衡"
        if value > 0.18:
            return "略偏冷号"
        return "偏冷号（补缺）"

    def _on_bias(self, value: int) -> None:
        self.params.hot_bias = value / 100.0
        self.bias_label.setText(self._bias_text(self.params.hot_bias))
        self._save()

    def _on_blue(self, index: int) -> None:
        self.params.blue_mode = BLUE_MODES[index][0]
        self._save()

    def _on_param(self, key: str, value: int) -> None:
        setattr(self.params, key, int(value))
        self._save()

    def _reset(self) -> None:
        default = RecParams()
        for field in ("hot_bias", "sum_lo", "sum_hi", "odd_min", "odd_max",
                      "zone_min", "zone_max", "max_overlap", "max_consecutive",
                      "min_span", "blue_mode"):
            setattr(self.params, field, getattr(default, field))
        self.params.validate()
        self._save()
        self.paramsChanged.emit()
        self._reload_widgets()

    def _reload_widgets(self) -> None:
        self.bias_slider.blockSignals(True)
        self.bias_slider.setValue(int(round(self.params.hot_bias * 100)))
        self.bias_slider.blockSignals(False)
        self.bias_label.setText(self._bias_text(self.params.hot_bias))

        for key, spin in self._spins.items():
            spin.blockSignals(True)
            spin.setValue(int(getattr(self.params, key)))
            spin.blockSignals(False)

        index = next((i for i, (k, _) in enumerate(BLUE_MODES)
                      if k == self.params.blue_mode), 0)
        self.blue_combo.blockSignals(True)
        self.blue_combo.setCurrentIndex(index)
        self.blue_combo.blockSignals(False)
        self.report_view.setFixedHeight(0)

    def _save(self) -> None:
        self.params.validate()
        save_params(self.params)
        self.paramsChanged.emit()

    def refresh_info(self) -> None:
        s = self.store.summary()
        if s["count"]:
            self.data_label.setText(
                f"共 {s['count']} 期：{s['first']} ~ {s['last']}，最近更新 {s['updated']}；"
                f"文件 {paths.DATA_DIR / 'ssq_history.csv'}"
            )
        else:
            self.data_label.setText("尚未加载数据，请先在「推荐」页点击「抓取新开奖」。")
        self.path_label.setText(f"数据目录：{paths.DATA_DIR}")

    def _open_folder(self) -> None:
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.DATA_DIR)))

    def _rebuild(self) -> None:
        if self.rebuild_worker and self.rebuild_worker.isRunning():
            return
        self.rebuild_btn.setEnabled(False)
        self.rebuild_btn.setText("重建中…")
        self.rebuild_worker = RebuildWorker(self)
        self.rebuild_worker.succeeded.connect(self._on_rebuilt)
        self.rebuild_worker.failed.connect(self._on_rebuild_failed)
        self.rebuild_worker.finished.connect(self._rebuild_done)
        self.rebuild_worker.start()

    def _rebuild_done(self) -> None:
        self.rebuild_btn.setEnabled(True)
        self.rebuild_btn.setText("重建数据集")

    def _on_rebuilt(self, info: dict) -> None:
        self.store.load(force=True)
        self.refresh_info()
        self.dataChanged.emit()

    def _on_rebuild_failed(self, message: str) -> None:
        self.report_view.setFixedHeight(90)
        self.report_view.setPlainText(f"重建失败：{message}")

    def _verify(self) -> None:
        if not self.store.available:
            self.report_view.setFixedHeight(60)
            self.report_view.setPlainText("没有可校验的数据。")
            return
        report = build.validate(self.store.df)
        lines = [f"{row['校验项']}：{row['结果']}" for _, row in report.iterrows()]
        self.report_view.setFixedHeight(min(240, 24 + 18 * len(lines)))
        self.report_view.setPlainText("\n".join(lines))
