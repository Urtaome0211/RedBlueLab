# -*- coding: utf-8 -*-
"""把主窗口的每个页面渲染成 PNG，用于无显示器环境下的界面自查。

注意：这里不能只用 QTest.qWait —— 它会独占 GIL 把后台线程饿死
（实测等待抓取时会从 0.004s 变成 9.7s）。统一用 pump()：处理事件 + 短暂睡眠。

用法：
    QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe tools\\screenshot.py [输出目录]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ssq.ui.main_window import MainWindow  # noqa: E402


def pump(app: QApplication, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def wait_for(app: QApplication, predicate, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.resize(1180, 900)
    window.show()
    pump(app, 0.6)

    # 等推荐线程与筛选器的组合表准备完
    wait_for(app, lambda: not (window.recommend_page.gen_worker
                               and window.recommend_page.gen_worker.isRunning()), 30)
    wait_for(app, lambda: window.filter_page.ready, 60)
    pump(app, 0.3)

    pages = [
        ("01_recommend", window.recommend_page),
        ("02_data", window.data_page),
        ("03_chart", window.chart_page),
        ("04_settings", window.settings_page),
    ]
    for name, page in pages:
        window.show_page(page)
        pump(app, 0.45)
        path = out / f"{name}.png"
        window.grab().save(str(path))
        print(f"saved {path}")

    # 走势图另外三张
    for key, name in (("red", "05_chart_red"), ("blue", "06_chart_blue"),
                      ("omit", "07_chart_omit")):
        window.show_page(window.chart_page)
        window.chart_page.select(key)
        pump(app, 0.35)
        path = out / f"{name}.png"
        window.grab().save(str(path))
        print(f"saved {path}")

    # 成绩单
    window.ledger_page.reload()
    window.show_page(window.ledger_page)
    pump(app, 0.45)
    path = out / "08_ledger.png"
    window.grab().save(str(path))
    print(f"saved {path}")

    # 筛选器（先生成几注，才有号码卡可看）
    window.filter_page.sample_tickets()
    window.show_page(window.filter_page)
    pump(app, 0.45)
    path = out / "09_filter.png"
    window.grab().save(str(path))
    print(f"saved {path}")

    # 大乐透：推荐 / 历史数据 / 走势图
    dlt_pages = [
        ("10_dlt_recommend", window.dlt_recommend_page),
        ("11_dlt_data", window.dlt_data_page),
        ("12_dlt_chart", window.dlt_chart_page),
    ]
    for name, page in dlt_pages:
        window.show_page(page)
        pump(app, 0.45)
        path = out / f"{name}.png"
        window.grab().save(str(path))
        print(f"saved {path}")

    for key, name in (("back", "13_dlt_chart_back"), ("sum", "14_dlt_chart_sum")):
        window.show_page(window.dlt_chart_page)
        window.dlt_chart_page.select(key)
        pump(app, 0.35)
        path = out / f"{name}.png"
        window.grab().save(str(path))
        print(f"saved {path}")

    # 新增彩种：推荐 + 历史（快乐8 / 福彩3D / 七乐彩 / 7星彩 / 排列3 / 排列5）
    for i, key in enumerate(("kl8", "fc3d", "qlc", "qxc", "pl3", "pl5"), start=15):
        rec_page, data_page = window.game_pages[key]
        for suffix, page in (("rec", rec_page), ("data", data_page)):
            window.show_page(page)
            pump(app, 0.45)
            path = out / f"{i:02d}_{key}_{suffix}.png"
            window.grab().save(str(path))
            print(f"saved {path}")

    window.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
