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
from games import spec as game_spec
from games import ui as game_ui
from ..config import load_params, save_params
from ..core import ledger as ledger_mod
from ..core.store import DataStore
from .pages.chart_page import ChartPage
from .pages.data_page import DataPage
from .pages.filter_page import FilterPage
from .pages.ledger_page import LedgerPage
from .pages.recommend_page import RecommendPage
from .pages.settings_page import SettingsPage
from .shell import GameShell


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

        # 新增彩种（快乐8 / 福彩3D / 七乐彩 / 7星彩 / 排列3 / 排列5）：每个两页
        self.game_pages: dict[str, tuple[game_ui.RecommendPage, game_ui.DataPage]] = {}
        for key in ("kl8", "fc3d", "qlc", "qxc", "pl3", "pl5"):
            self.game_pages[key] = game_ui.create_pages(key)

        self.dlt_recommend_page = DltRecommendPage(self.dlt_store, self.dlt_params, self)
        self.dlt_data_page = DltDataPage(self.dlt_store, self)
        self.dlt_chart_page = DltChartPage(self.dlt_store, self)

        # 每个彩种一个导航项，页面内用「模块」下拉框切换
        self.shells: dict[str, GameShell] = {}
        self.ssq_shell = GameShell("双色球", [
            ("推荐", self.recommend_page),
            ("成绩单", self.ledger_page),
            ("筛选器", self.filter_page),
            ("历史", self.data_page),
            ("走势", self.chart_page),
        ], self)
        self.shells["ssq"] = self.ssq_shell

        self.dlt_shell = GameShell("超级大乐透", [
            ("推荐", self.dlt_recommend_page),
            ("历史", self.dlt_data_page),
            ("走势", self.dlt_chart_page),
        ], self)
        self.shells["dlt"] = self.dlt_shell

        for key in ("kl8", "fc3d", "qlc", "qxc", "pl3", "pl5"):
            spec = game_spec.get(key)
            rec_page, data_page = self.game_pages[key]
            self.shells[key] = GameShell(spec.name, [("推荐", rec_page), ("历史", data_page)], self)
            rec_page.dataChanged.connect(self._on_game_data_changed)

        nav = self.navigationInterface
        nav.addItemHeader("福彩", NavigationItemPosition.SCROLL)
        self.addSubInterface(self.ssq_shell, FIF.HOME, "双色球",
                             NavigationItemPosition.SCROLL)
        for key in ("kl8", "fc3d", "qlc"):
            self.addSubInterface(self.shells[key], FIF.GAME, game_spec.get(key).name,
                                 NavigationItemPosition.SCROLL)

        nav.addItemHeader("体彩", NavigationItemPosition.SCROLL)
        self.addSubInterface(self.dlt_shell, FIF.GAME, "超级大乐透",
                             NavigationItemPosition.SCROLL)
        for key in ("qxc", "pl3", "pl5"):
            self.addSubInterface(self.shells[key], FIF.GAME, game_spec.get(key).name,
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
        # 这些页面在构造时已经生成过推荐，这里不再重复触发

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

    def _on_game_data_changed(self) -> None:
        for rec_page, data_page in self.game_pages.values():
            data_page.reload()

    def _on_dlt_data_changed(self) -> None:
        self.dlt_data_page.reload()
        self.dlt_chart_page.reload()

    def _on_params_changed(self) -> None:
        save_params(self.params)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """窗口关闭前等后台线程收尾，否则 Qt 会带着运行中的 QThread 退出并崩溃。"""
        self.shutdown()
        super().closeEvent(event)

    def show_page(self, widget) -> bool:
        """切到某个页面所在的彩种 + 模块（截图脚本 / 自检用）。"""
        for shell in self.shells.values():
            if shell.show_page(widget):
                self.switchTo(shell)
                return True
        self.switchTo(widget)   # 不在任何彩种外壳里的页面（如设置）
        return True

    def shutdown(self) -> None:
        workers = [self.recommend_page.worker, self.recommend_page.gen_worker,
                   self.filter_page.worker, self.dlt_recommend_page.worker,
                   *[rec.worker for rec, _ in self.game_pages.values()]]
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
