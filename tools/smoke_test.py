# -*- coding: utf-8 -*-
"""无界面功能自检：推荐生成、算法切换、参数联动、图表切换、抓取新开奖。

用法：
    QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe tools\\smoke_test.py
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

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ssq.core import universal  # noqa: E402
from ssq.ui.main_window import MainWindow  # noqa: E402

FAILED: list[str] = []


def pump(seconds: float) -> None:
    """处理事件但不使用 QTest.qWait——后者会长时间独占 GIL，饿死后台线程。"""
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)


def wait_gen(page, timeout: float = 120.0) -> None:
    """等推荐线程跑完（generate() 是异步的）。"""
    deadline = time.time() + timeout
    worker = page.gen_worker
    while worker is not None and worker.isRunning() and time.time() < deadline:
        pump(100 / 1000)
    pump(250 / 1000)


def check(ok: bool, message: str) -> None:
    print(("  OK   " if ok else "  FAIL ") + message)
    if not ok:
        FAILED.append(message)


def main() -> int:
    app = QApplication(sys.argv[:1])
    picks = ROOT / "picks.json"
    backup = picks.read_bytes() if picks.exists() else None

    win = MainWindow()
    win.resize(1180, 820)
    win.show()
    pump(400 / 1000)

    store = win.store
    rec_page = win.recommend_page
    check(store.available and store.count > 2000, f"数据集已加载：{store.count} 期")

    # ---------------- 推荐 ----------------
    rec_page.count_spin.setValue(5)
    rec_page.kind_combo.setCurrentIndex(0)   # 统计打分
    rec_page.generate()
    wait_gen(rec_page)
    stats_tickets = list(rec_page.tickets)
    check(len(stats_tickets) == 5, f"统计打分生成 {len(stats_tickets)} 注")
    check(all(len(t.reds) == 6 and 1 <= t.blue <= 16 for t in stats_tickets),
          "号码结构合法（6 红 1 蓝，范围正确）")
    check(len({tuple(t.reds) for t in stats_tickets}) == 5, "5 注互不重复")
    check(all("含热号" in t.reason or "含冷号" in t.reason
              or "分散度较高" in t.reason for t in stats_tickets), "每注都有理由文案")

    rec_page.kind_combo.setCurrentIndex(1)   # 约束随机
    rec_page.generate()
    wait_gen(rec_page)
    random_tickets = list(rec_page.tickets)
    check(len(random_tickets) == 5, f"约束随机生成 {len(random_tickets)} 注")
    check(all("含热号" not in t.reason for t in random_tickets),
          "约束随机不显示热号理由")
    p = rec_page.params
    check(all(p.sum_lo <= sum(t.reds) <= p.sum_hi for t in random_tickets), "和值落在参数区间")
    check(all(t.composition for t in random_tickets), "形态描述非空")

    rec_page.kind_combo.setCurrentIndex(0)
    rec_page.generate()
    wait_gen(rec_page)
    check(win.recommend_page.tickets_layout.count() == 5, "推荐卡片已渲染 5 张")

    # ---------------- 覆盖优化 ----------------
    rec_page.kind_combo.setCurrentIndex(2)   # 覆盖优化
    rec_page.pool_spin.setValue(18)
    rec_page.count_spin.setValue(5)
    rec_page.generate()
    wait_gen(rec_page)
    cov = list(rec_page.tickets)
    info = rec_page.last_info
    check(len(cov) == 5, f"覆盖优化生成 {len(cov)} 注")
    check(info.get("floor", 0) >= 2, f"覆盖保底 {info.get('floor')} 红（池 {info.get('pool')} 个号）")
    check(all("覆盖" in t.reason for t in cov), "覆盖优化的每注理由都写了覆盖信息")

    # ---------------- 成绩单 ----------------
    led = rec_page.ledger
    before_n = len(led.records)
    rec_page.record_check.setChecked(True)
    rec_page.kind_combo.setCurrentIndex(0)
    rec_page.generate()
    wait_gen(rec_page)
    added = len(led.records) - before_n
    check(added >= 1, f"推荐结果已记入成绩单（新增 {added} 批）")
    win.ledger_page.reload()
    pump(80 / 1000)
    check(win.ledger_page.table.rowCount() == len(led.records),
          f"成绩单表格行数 {win.ledger_page.table.rowCount()} 与记录数一致")

    from ssq.core import ledger as ledger_mod
    draw = store.latest()
    level, hit, _ = ledger_mod.judge(list(draw.reds), draw.blue, list(draw.reds), draw.blue)
    check(level == 1 and hit == 6, "judge：命中当期中奖号码即一等奖")
    level2, hit2, _ = ledger_mod.judge([1, 2, 3, 4, 5, 6], 16,
                                       [1, 2, 3, 4, 5, 6], 15)
    check(level2 == 2 and hit2 == 6, "judge：6 红 0 蓝 = 二等奖")
    level3, _, _ = ledger_mod.judge([7, 8, 9, 10, 11, 12], 16,
                                    [1, 2, 3, 4, 5, 6], 15)
    check(level3 is None, "judge：红球全不中且蓝球不对 = 未中奖")

    # ---------------- 号码筛选器 ----------------
    fp = win.filter_page
    deadline = time.time() + 120
    while fp.worker is not None and fp.worker.isRunning() and time.time() < deadline:
        pump(150 / 1000)
    pump(300 / 1000)
    check(fp.ready, "筛选器全组合已就绪")
    base_n = universal.count(fp._spec(), fp._prev_reds())
    check(base_n == 603_418, f"默认条件剩余 {base_n:,} 注")
    fp.sp_sum[0].setValue(100)
    fp.sp_sum[1].setValue(110)
    pump(800 / 1000)
    tighter = universal.count(fp._spec(), fp._prev_reds())
    check(0 < tighter < base_n, f"收紧和值 100-110 后剩余 {tighter:,} 注")
    fp.sample_tickets()
    pump(200 / 1000)
    got = list(fp.tickets)
    check(len(got) == 5, f"随机取 5 注（实际 {len(got)}）")
    check(all(100 <= sum(t.reds) <= 110 for t in got), "抽样号码满足和值条件")
    check(fp.tickets_layout.count() == 5, "筛选器号码卡片渲染 5 张")
    fp.reset()
    pump(800 / 1000)
    check(universal.count(fp._spec(), fp._prev_reds()) == base_n, "恢复默认后回到默认剩余注数")

    # ---------------- 设置联动 ----------------
    win.settings_page._spins["sum_lo"].setValue(70)
    pump(50 / 1000)
    check(win.params.sum_lo == 70, "设置页改和值下限后参数同步")
    win.settings_page._reset()
    pump(50 / 1000)
    check(win.params.sum_lo == 80, "恢复默认后参数回到 80")
    check(win.settings_page._spins["sum_lo"].value() == 80, "恢复默认后控件同步刷新")

    # ---------------- 图表 ----------------
    for key in ("sum", "red", "blue", "omit"):
        win.chart_page.select(key)
        pump(60 / 1000)
        check(win.chart_page.current == key, f"走势图切换到 {key}")

    # ---------------- 历史数据表 ----------------
    win.data_page.reload()
    pump(50 / 1000)
    check(win.data_page.model.rowCount() > 0, f"表格行数 {win.data_page.model.rowCount()}")

    # ---------------- 抓取 ----------------
    before = store.count
    rec_page.start_crawl()
    deadline = time.time() + 240
    worker = rec_page.worker
    while worker is not None and worker.isRunning() and time.time() < deadline:
        pump(200 / 1000)
    pump(800 / 1000)
    after = store.count
    print(f"  抓取状态：{rec_page.status_label.text()}")
    check(not (worker and worker.isRunning()), "抓取线程已结束")
    check(after >= before, f"抓取后数据未减少（{before} → {after} 期）")
    check(rec_page.footer.text().startswith("数据："), "底部期望回报信息已更新")

    # ---------------- 大乐透 ----------------
    dlt = win.dlt_store
    check(dlt.count > 2000, f"大乐透数据集已加载：{dlt.count} 期")
    d = dlt.latest()
    check(d is not None and len(d.front) == 5 and len(d.back) == 2,
          f"最新一期 {d.issue}：{d.front_text} + {d.back_text}")

    from dlt.recommend import DltParams, expected_value, recommend
    ev = expected_value(dlt)
    check(ev["combos"] == 21_425_712, f"大乐透组合数 {ev['combos']:,}")
    check(0.3 < ev["return_rate"] < 0.8, f"估算返还率 {ev['return_rate']:.1%}")

    for kind in ("stats", "random"):
        tickets = recommend(dlt, kind, DltParams(n_tickets=5, seed=11))
        check(len(tickets) == 5, f"大乐透·{kind} 生成 {len(tickets)} 注")
        check(all(len(t.front) == 5 and len(t.back) == 2 for t in tickets),
              "前区 5 个、后区 2 个")
        check(all(len(set(t.front)) == 5 and all(1 <= n <= 35 for n in t.front)
                  and all(1 <= n <= 12 for n in t.back) for t in tickets),
              "号码范围合法且不重复")
        check(all(60 <= t.total <= 135 and 1 <= t.odd <= 4 for t in tickets),
              "和值与奇偶满足默认区间")
        check(len({tuple(t.front) for t in tickets}) == 5, "注间前区不重复")

    dp = win.dlt_recommend_page
    dp.generate()
    pump(80 / 1000)
    check(len(dp.tickets) == 5, f"大乐透推荐页生成 {len(dp.tickets)} 注")
    check(dp.tickets_layout.count() == 5, "大乐透推荐卡片渲染 5 张")

    win.dlt_data_page.reload()
    pump(60 / 1000)
    check(win.dlt_data_page.table.rowCount() > 0,
          f"大乐透表格行数 {win.dlt_data_page.table.rowCount()}")

    for key, _label in (("front", "前区频次"), ("back", "后区频次"), ("sum", "和值走势")):
        win.dlt_chart_page.select(key)
        pump(60 / 1000)
        check(win.dlt_chart_page.segment.currentRouteKey() == key,
              f"大乐透走势图切换到 {key}")

    print()
    if backup is not None:
        picks.write_bytes(backup)
    elif picks.exists():
        picks.unlink()
    win.shutdown()
    win.close()

    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

