# -*- coding: utf-8 -*-
"""工具函数：金额/数量格式化、线程 worker。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .. import paths
from ..core import build, fetch, store as store_mod


def fmt_money(v: float | int | None) -> str:
    if v is None:
        return "-"
    v = float(v)
    if v >= 1e8:
        return f"{v / 1e8:.2f} 亿"
    if v >= 1e4:
        return f"{v / 1e4:.0f} 万"
    return f"{v:,.0f}"


def fmt_count(v: int | None) -> str:
    return "-" if v is None else f"{v:,}"


class CrawlWorker(QThread):
    """后台抓取 + 重建数据集，避免阻塞界面。"""

    message = Signal(str)
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, store: store_mod.DataStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store

    def run(self) -> None:  # noqa: D401
        try:
            before = set(self.store.issues())
            self.message.emit("连接官网接口…")
            meta = fetch.crawl(log=self.message.emit)
            self.message.emit("解析并重建数据集…")
            res = build.build(data_dir=paths.DATA_DIR, export_xlsx=True,
                              log=self.message.emit)
            issues = set(res["df"]["期号"])
            new = sorted(issues - before, reverse=True)
            self.succeeded.emit({"total": len(res["df"]), "new": new, "meta": meta,
                                 "range": (str(res["df"]["开奖日期"].min()),
                                           str(res["df"]["开奖日期"].max()))})
        except Exception as exc:  # noqa: BLE001 - 界面需要显示任何异常
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class RebuildWorker(QThread):
    """只重建数据集（不联网）。"""

    message = Signal(str)
    succeeded = Signal(dict)
    failed = Signal(str)

    def run(self) -> None:
        try:
            res = build.build(data_dir=paths.DATA_DIR, export_xlsx=True,
                              log=self.message.emit)
            self.succeeded.emit({"total": len(res["df"]),
                                 "range": (str(res["df"]["开奖日期"].min()),
                                           str(res["df"]["开奖日期"].max()))})
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class RecommendWorker(QThread):
    """后台生成推荐（覆盖优化要跑几百毫秒的局部搜索，放线程里免得界面卡住）。"""

    done = Signal(list, dict)          # tickets, info
    failed = Signal(str)

    def __init__(self, store: store_mod.DataStore, kind: str, params,
                 pool_size: int = 18, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.kind = kind
        self.params = params
        self.pool_size = pool_size

    def run(self) -> None:
        from ..core import recommend as rec

        try:
            if self.kind == "coverage":
                tickets, info = rec.recommend_coverage(
                    self.store, self.params, pool_size=self.pool_size)
            else:
                tickets = rec.recommend(self.store, self.kind, self.params)
                info = {}
            self.done.emit(tickets, info)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class FilterWorker(QThread):
    """后台准备全组合表 / 计算筛选结果。"""

    message = Signal(str)
    ready = Signal()
    failed = Signal(str)

    def run(self) -> None:
        from ..core import universal

        try:
            universal.all_combos(progress=lambda m: self.message.emit(m))
            self.message.emit("计算组合指标…")
            universal.metrics()
            self.ready.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
