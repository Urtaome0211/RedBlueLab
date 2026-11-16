# -*- coding: utf-8 -*-
"""推荐成绩单：把生成过的号码存档，开奖后自动结算。

存档文件是 ``<app_root>/picks.json``，结构::

    {"version": 1,
     "items": [
       {"id": "B20261108-113012", "created": "2026-11-08 11:30",
        "base_issue": "2026127", "base_date": "2026-11-05",
        "kind": "stats", "note": "统计打分 · 5 注 · …",
        "tickets": [{"reds": [3, 5, 12, 18, 22, 31], "blue": 7}, …],
        "cost": 10,
        "settled": {"issue": "2026128", "date": "2026-11-08",
                    "reds": [..], "blue": 3, "prize": 20,
                    "levels": {"6": 2}, "hits": [{"level": 6, "money": 5}, …]}}
     ]}

结算规则按《中国福利彩票双色球游戏规则》的固定奖级：三~六等奖金额固定，
一、二等奖按该期官方公布的「单注奖金」取值（复式拆成多注后逐注计算）。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .. import paths
from .recommend import RecParams, Ticket
from .store import DataStore

PICKS_FILENAME = "picks.json"
MAX_RECORDS = 300

# (红球命中, 蓝球是否命中) -> 奖级
PRIZE_TABLE: dict[tuple[int, int], int] = {
    (6, 1): 1, (6, 0): 2,
    (5, 1): 3, (5, 0): 4, (4, 1): 4,
    (4, 0): 5, (3, 1): 5,
    (2, 1): 6, (1, 1): 6, (0, 1): 6,
}

FIXED_MONEY = {3: 3000, 4: 200, 5: 10, 6: 5}
LEVEL_NAMES = {1: "一等奖", 2: "二等奖", 3: "三等奖", 4: "四等奖", 5: "五等奖", 6: "六等奖"}


def _float_money(df, issue: str, column: str) -> float | None:
    try:
        row = df.loc[df["期号"].astype(str) == str(issue)].iloc[0]
    except (KeyError, IndexError):
        return None
    value = row.get(column)
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def judge(reds: Sequence[int], blue: int,
          draw_reds: Sequence[int], draw_blue: int) -> tuple[int | None, int, int]:
    """返回 (奖级, 命中红球数, 是否命中蓝球)。未中奖时奖级为 None。"""
    hit = len(set(int(x) for x in reds) & set(int(x) for x in draw_reds))
    blue_hit = int(blue) == int(draw_blue)
    level = PRIZE_TABLE.get((hit, 1 if blue_hit else 0))
    return level, hit, 1 if blue_hit else 0


def ticket_money(level: int | None, df, issue: str) -> float:
    """按奖级取单注奖金。"""
    if level is None:
        return 0.0
    if level in FIXED_MONEY:
        return float(FIXED_MONEY[level])
    column = f"{LEVEL_NAMES[level]}单注奖金(元)"
    value = _float_money(df, issue, column)
    if value is None:
        value = 7_000_000.0 if level == 1 else 200_000.0
    return value


class Ledger:
    """推荐存档与结算。所有写操作立即落盘（失败静默，不影响主流程）。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or (paths.ROOT / PICKS_FILENAME))
        self.records: list[dict] = []
        self.load()

    # ---------------- 读写 ----------------
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.records = []
            return
        items = raw.get("items") if isinstance(raw, dict) else None
        self.records = [r for r in items if isinstance(r, dict) and r.get("tickets")] \
            if isinstance(items, list) else []

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "items": self.records[-MAX_RECORDS:]}
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        except OSError:
            pass

    # ---------------- 写入 ----------------
    def add_batch(self, store: DataStore, tickets: Iterable[Ticket], kind: str,
                  params: RecParams | None = None) -> dict | None:
        """记录一批推荐。相同基准期号 + 相同号码会自动去重，返回 None。"""
        tickets = list(tickets)
        if not tickets or not store.available:
            return None
        latest = store.latest()
        base_issue = latest.issue if latest else ""
        base_date = latest.date if latest else ""
        key = sorted((tuple(t.reds), int(t.blue)) for t in tickets)

        for rec in self.records:
            if rec.get("base_issue") != base_issue:
                continue
            old = sorted((tuple(int(x) for x in t["reds"]), int(t["blue"]))
                         for t in rec.get("tickets", []))
            if old == key:
                return None

        now = datetime.now()
        record = {
            "id": f"B{now:%Y%m%d-%H%M%S}",
            "created": now.strftime("%Y-%m-%d %H:%M"),
            "base_issue": base_issue,
            "base_date": base_date,
            "kind": kind,
            "note": _describe(kind, params, len(tickets)),
            "tickets": [{"reds": [int(x) for x in t.reds], "blue": int(t.blue)}
                        for t in tickets],
            "cost": 2 * len(tickets),
            "settled": None,
        }
        self.records.append(record)
        self.save()
        return record

    def settle(self, store: DataStore) -> int:
        """给所有能结算的记录结算，返回新结算的批次数。"""
        if not store.available:
            return 0
        asc = store.asc
        order = {str(issue): i for i, issue in enumerate(asc["期号"])}
        df = store.df
        done = 0
        for rec in self.records:
            if rec.get("settled"):
                continue
            pos = order.get(str(rec.get("base_issue")))
            if pos is None or pos + 1 >= len(asc):
                continue
            row = asc.iloc[pos + 1]
            issue = str(row["期号"])
            draw_reds = [int(x) for x in str(row["红球"]).split(",")]
            draw_blue = int(row["蓝球"])
            hits = []
            levels: dict[str, int] = {}
            prize = 0.0
            for t in rec["tickets"]:
                level, _hit, _blue = judge(t["reds"], t["blue"], draw_reds, draw_blue)
                money = ticket_money(level, df, issue)
                prize += money
                if level is not None:
                    levels[str(level)] = levels.get(str(level), 0) + 1
                hits.append({"level": level, "money": round(money, 2)})
            rec["settled"] = {
                "issue": issue,
                "date": str(row["开奖日期"]),
                "reds": draw_reds,
                "blue": draw_blue,
                "prize": round(prize, 2),
                "levels": levels,
                "hits": hits,
            }
            done += 1
        if done:
            self.save()
        return done

    def clear(self) -> None:
        self.records = []
        self.save()

    # ---------------- 统计 ----------------
    def stats(self) -> dict:
        batches = len(self.records)
        settled = [r for r in self.records if r.get("settled")]
        tickets = sum(len(r.get("tickets", [])) for r in self.records)
        settled_tickets = sum(len(r.get("tickets", [])) for r in settled)
        cost = sum(int(r.get("cost", 0)) for r in self.records)
        settled_cost = sum(int(r.get("cost", 0)) for r in settled)
        prize = sum(float(r["settled"].get("prize", 0)) for r in settled)
        levels: dict[int, int] = {}
        best = 0.0
        winning_tickets = 0
        for rec in settled:
            for level_str, count in rec["settled"].get("levels", {}).items():
                levels[int(level_str)] = levels.get(int(level_str), 0) + int(count)
            best = max(best, float(rec["settled"].get("prize", 0)))
            winning_tickets += sum(int(c) for c in rec["settled"].get("levels", {}).values())
        return {
            "batches": batches,
            "settled_batches": len(settled),
            "pending_batches": batches - len(settled),
            "tickets": tickets,
            "settled_tickets": settled_tickets,
            "cost": cost,
            "settled_cost": settled_cost,
            "prize": round(prize, 2),
            "profit": round(prize - cost, 2),
            "roi": (prize / cost) if cost else 0.0,
            "levels": levels,
            "best": round(best, 2),
            "winning_tickets": winning_tickets,
            "hit_rate": (winning_tickets / settled_tickets) if settled_tickets else 0.0,
        }

    def recent(self, n: int = 6) -> list[dict]:
        return list(reversed(self.records[-n:]))


def _describe(kind: str, params: RecParams | None, count: int) -> str:
    algo = {"stats": "统计打分", "random": "约束随机", "coverage": "覆盖优化"}.get(kind, kind)
    if params is None:
        return f"{algo} · {count} 注"
    return (f"{algo} · {count} 注 · 和值 {params.sum_lo}-{params.sum_hi} · "
            f"奇偶 {params.odd_min}-{params.odd_max}")


def summarize(record: dict) -> str:
    """一句话描述一条记录的结果（给界面列表用）。"""
    settled = record.get("settled")
    if not settled:
        return f"{record['created']} · {len(record['tickets'])} 注 · 待开奖"
    prize = float(settled.get("prize", 0))
    cost = int(record.get("cost", 0))
    levels = settled.get("levels", {})
    level_text = "、".join(f"{LEVEL_NAMES[int(k)]}×{v}" for k, v in sorted(levels.items())) \
        if levels else "未中奖"
    return (f"{record['created']} · {len(record['tickets'])} 注 · 开奖后 {level_text} · "
            f"中 {prize:,.0f} 元（投入 {cost} 元，{prize - cost:+,.0f}）")


def export_text(ledger: Ledger) -> str:
    lines = ["批次,创建时间,基准期号,算法,注数,投入,开奖期号,中奖金额,盈亏,奖级"]
    for rec in ledger.records:
        s = rec.get("settled") or {}
        levels = "/".join(f"{LEVEL_NAMES[int(k)]}x{v}" for k, v in sorted(s.get("levels", {}).items()))
        lines.append(",".join([
            rec.get("id", ""), rec.get("created", ""), rec.get("base_issue", ""),
            rec.get("note", "").split(" · ")[0], str(len(rec.get("tickets", []))),
            str(rec.get("cost", 0)), s.get("issue", ""), f"{float(s.get('prize', 0)):.0f}",
            f"{float(s.get('prize', 0)) - int(rec.get('cost', 0)):.0f}", levels,
        ]))
    return "\n".join(lines)


def default_path() -> Path:
    return paths.ROOT / PICKS_FILENAME


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


__all__ = ["Ledger", "judge", "ticket_money", "summarize", "export_text", "PRIZE_TABLE",
           "LEVEL_NAMES", "FIXED_MONEY", "default_path", "asdict"]
