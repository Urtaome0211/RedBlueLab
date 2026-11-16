# -*- coding: utf-8 -*-
"""生成一份演示用成绩单：两批推荐，其中一批已按真实开奖结算（用于截图/文档）。

用法：
    .venv\\Scripts\\python.exe tools\\demo_ledger.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ssq.core import recommend as rec  # noqa: E402
from ssq.core.ledger import Ledger  # noqa: E402
from ssq.core.store import DataStore  # noqa: E402

# 2026127 期真实开奖：13 14 19 25 29 32 + 12
DEMO_TICKETS = [
    ((13, 14, 19, 25, 2, 4), 12),     # 4 红 + 蓝 → 四等奖
    ((13, 14, 19, 2, 4, 6), 12),      # 3 红 + 蓝 → 五等奖
    ((13, 25, 29, 3, 5, 7), 12),      # 3 红 + 蓝 → 五等奖
    ((13, 14, 8, 10, 16, 18), 12),    # 2 红 + 蓝 → 六等奖
    ((2, 4, 6, 8, 10, 16), 3),        # 未中
]


def main() -> int:
    store = DataStore()
    store.load()
    ledger = Ledger()
    ledger.clear()

    params = rec.RecParams(n_tickets=5, seed=20261105)
    tickets = [rec.Ticket(reds, blue, reason="覆盖包 18 个号")
               for reds, blue in DEMO_TICKETS]
    ledger.add_batch(store, tickets, "stats", params)

    cov_params = rec.RecParams(n_tickets=5, seed=20261104)
    cov_tickets, _info = rec.recommend_coverage(store, cov_params, pool_size=18)
    ledger.add_batch(store, cov_tickets, "coverage", cov_params)

    # 第一批挂在 2026126 期之后，用真实开出的 2026127 期结算
    ledger.records[0]["base_issue"] = "2026126"
    ledger.save()
    settled = ledger.settle(store)
    stats = ledger.stats()

    print(f"结算 {settled} 批 · 共 {stats['batches']} 批 / {stats['tickets']} 注")
    print(f"投入 {stats['cost']} 元 · 中奖 {stats['prize']} 元 · "
          f"盈亏 {stats['profit']} 元 · 返还率 {stats['roi']:.0%}")
    for record in ledger.records:
        print(" ", record["id"], record["kind"], record.get("base_issue"),
              "→", (record.get("settled") or {}).get("issue", "待开奖"),
              (record.get("settled") or {}).get("prize", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
