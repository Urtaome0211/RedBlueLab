# -*- coding: utf-8 -*-
"""主窗口：Fluent 导航 + 四个页面。"""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qfluentwidgets import (FluentWindow, FluentIcon as FIF, NavigationItemPosition,
                            setTheme, setThemeColor, Theme)

from .. import APP_TITLE, __version__, paths
from dlt.recommend import DltParams
from dlt.store import DltStore
from dlt.ui import DltChartPage, DltDataPage, DltRecommendPage
from ..config import load_params, save_params
from ..core import ledger as ledger_mod
from ..core.store import DataStore
from .pages.chart_page import ChartPage
from .pages.data_page import DataPage
from .pages.filter_page import FilterPage
from .pages.ledger_page import LedgerPage
from .pages.recommend_page import RecommendPage
from .pages.settings_page import SettingsPage


def make_icon() -> QIcon:
    """画一个「红球」图标，避免依赖外部图片资源。"""
    pix = QPixmap(128, 128)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#E1251B"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(6, 6, 116, 116)
    font = QFont("Microsoft YaHei")
    font.setPointSize(40)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(pix.rect(), Qt.AlignCenter, "RB")
    painter.end()
    return QIcon(pix)


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        paths.ensure_data_dir()
        self.store = DataStore()
        self.params = load_params()

        self.dlt_store = DltStore()
        self.dlt_store.load()
        self.dlt_params = DltParams()

        self.recommend_page = RecommendPage(self.store, self.params, self)
        self.ledger_page = LedgerPage(self.store, self.recommend_page.ledger, self)
        self.filter_page = FilterPage(self.store, self)
        self.data_page = DataPage(self.store, self)
        self.chart_page = ChartPage(self.store, self)
        self.settings_page = SettingsPage(self.store, self.params, self)

        self.dlt_recommend_page = DltRecommendPage(self.dlt_store, self.dlt_params, self)
        self.dlt_data_page = DltDataPage(self.dlt_store, self)
        self.dlt_chart_page = DltChartPage(self.dlt_store, self)

        nav = self.navigationInterface
        nav.addItemHeader("双色球", NavigationItemPosition.SCROLL)
        self.addSubInterface(self.recommend_page, FIF.HOME, "推荐",
                             NavigationItemPosition.SCROLL)
        self.addSubInterface(self.ledger_page, FIF.HISTORY, "成绩单",
                             NavigationItemPosition.SCROLL)
        self.addSubInterface(self.filter_page, FIF.FILTER, "筛选器",
                             NavigationItemPosition.SCROLL)
        self.addSubInterface(self.data_page, FIF.DOCUMENT, "历史数据",
                             NavigationItemPosition.SCROLL)
        self.addSubInterface(self.chart_page, FIF.PIE_SINGLE, "走势图",
                             NavigationItemPosition.SCROLL)

        nav.addItemHeader("大乐透", NavigationItemPosition.SCROLL)
        self.addSubInterface(self.dlt_recommend_page, FIF.GAME, "推荐",
                             NavigationItemPosition.SCROLL)
        self.addSubInterface(self.dlt_data_page, FIF.DOCUMENT, "历史数据",
                             NavigationItemPosition.SCROLL)
        self.addSubInterface(self.dlt_chart_page, FIF.PIE_SINGLE, "走势图",
                             NavigationItemPosition.SCROLL)

        self.addSubInterface(self.settings_page, FIF.SETTING, "设置",
                             NavigationItemPosition.BOTTOM)

        self.recommend_page.dataChanged.connect(self._on_data_changed)
        self.dlt_recommend_page.dataChanged.connect(self._on_dlt_data_changed)
        self.recommend_page.recorded.connect(self.ledger_page.reload)
        self.settings_page.dataChanged.connect(self._on_data_changed)
        self.settings_page.paramsChanged.connect(self._on_params_changed)

        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.setWindowIcon(make_icon())
        self.resize(1180, 820)
        self.navigationInterface.setExpandWidth(190)
        self.navigationInterface.expand(useAni=False)

        if self.store.available:
            self.recommend_page.generate(auto=True)
        if self.dlt_store.available:
            self.dlt_recommend_page.generate()

    def _on_data_changed(self) -> None:
        self.data_page.reload()
        self.chart_page.reload()
        self.settings_page.refresh_info()
        try:  # 有新开奖就顺手结算成绩单
            self.recommend_page.ledger.settle(self.store)
        except Exception:  # noqa: BLE001 - 结算失败不该影响界面
            pass
        self.ledger_page.reload()
        self.filter_page.schedule()

    def _on_dlt_data_changed(self) -> None:
        self.dlt_data_page.reload()
        self.dlt_chart_page.reload()

    def _on_params_changed(self) -> None:
        save_params(self.params)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """窗口关闭前等后台线程收尾，否则 Qt 会带着运行中的 QThread 退出并崩溃。"""
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        workers = [self.recommend_page.worker, self.recommend_page.gen_worker,
                   self.filter_page.worker, self.dlt_recommend_page.worker]
        for worker in workers:
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(5000)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    app.setWindowIcon(make_icon())

    setThemeColor("#C00000")
    setTheme(Theme.LIGHT)
    font = QFont("Microsoft YaHei UI")
    font.setPointSize(9)
    app.setFont(font)

    window = MainWindow()
    window.show()

    # 供打包自检：--selftest 建一次窗口后正常收尾退出
    if "--selftest" in argv:
        window.shutdown()
        window.close()
        app.processEvents()
        return 0
    return app.exec()
