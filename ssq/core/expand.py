# -*- coding: utf-8 -*-
"""手工组合工具：复式、胆拖的展开与号码解析。

复式：红球选 r 个（r≥6），所有 C(r,6) 种组合，各配 k 个蓝球。
胆拖：红球胆码 d 个（1~5）必须每注都含，拖码 t 个里再选 6-d 个。
两者都可能展开成上千注，这里统一设上限，超出只做预览。
"""
from __future__ import annotations

import re
from itertools import combinations

from .recommend import Ticket

RED_MAX = 33
BLUE_MAX = 16
MAX_TICKETS = 20_000


def parse_numbers(text: str) -> list[int]:
    """从 "01 05 12" / "1,2,3" / "01-05" 这类输入里解析号码（去重、升序）。"""
    out: set[int] = set()
    for token in re.split(r"[\s,，、;；/]+", (text or "").strip()):
        if not token:
            continue
        m = re.fullmatch(r"(\d{1,2})\s*[-~至]\s*(\d{1,2})", token)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            out.update(range(lo, hi + 1))
            continue
        if token.isdigit():
            out.add(int(token))
    return sorted(n for n in out if 1 <= n <= RED_MAX)


def parse_blues(text: str) -> list[int]:
    return sorted(n for n in parse_numbers(text) if 1 <= n <= BLUE_MAX)


def combo_count(n_reds: int, n_dan: int, n_tuo: int) -> int:
    """复式/胆拖的红球组合数（不含蓝球）。"""
    from math import comb
    if n_reds:
        return comb(n_reds, 6) if n_reds >= 6 else 0
    need = 6 - n_dan
    return comb(n_tuo, need) if 0 <= need <= n_tuo else 0


def expand_fushi(reds: list[int], blues: list[int],
                 limit: int = MAX_TICKETS) -> tuple[list[Ticket], int]:
    reds = sorted(set(reds))
    blues = sorted(set(blues)) or [1]
    if len(reds) < 6:
        return [], 0
    total = combo_count(len(reds), 0, 0) * len(blues)
    tickets: list[Ticket] = []
    for red_combo in combinations(reds, 6):
        for blue in blues:
            if len(tickets) >= limit:
                return tickets, total
            tickets.append(Ticket(tuple(red_combo), blue,
                                  reason=f"复式 {len(reds)} 红 × {len(blues)} 蓝"))
    return tickets, total


def expand_dantuo(dan: list[int], tuo: list[int], blues: list[int],
                  limit: int = MAX_TICKETS) -> tuple[list[Ticket], int]:
    dan = sorted(set(dan))
    tuo = sorted(set(tuo) - set(dan))
    blues = sorted(set(blues)) or [1]
    need = 6 - len(dan)
    if not dan or need <= 0 or need > len(tuo):
        return [], 0
    total = combo_count(0, len(dan), len(tuo)) * len(blues)
    tickets: list[Ticket] = []
    for extra in combinations(tuo, need):
        reds = tuple(sorted(dan + list(extra)))
        for blue in blues:
            if len(tickets) >= limit:
                return tickets, total
            tickets.append(Ticket(reds, blue,
                                  reason=f"胆拖 胆{len(dan)}+拖{len(tuo)} × {len(blues)} 蓝"))
    return tickets, total


def check_dantuo(dan: list[int], tuo: list[int]) -> str | None:
    """返回错误提示，None 表示可以展开。"""
    dan = sorted(set(dan))
    tuo = sorted(set(tuo) - set(dan))
    if not dan:
        return "请至少选 1 个胆码"
    if len(dan) > 5:
        return "胆码最多 5 个（否则凑不齐 6 个红球）"
    if len(tuo) < 6 - len(dan):
        return f"拖码不够：{len(dan)} 个胆码还需要 {6 - len(dan)} 个拖码"
    if len(dan) + len(tuo) > RED_MAX:
        return "号码超范围"
    return None


def check_fushi(reds: list[int], blues: list[int]) -> str | None:
    if len(reds) < 6:
        return "复式至少选 6 个红球"
    if not blues:
        return "请至少选 1 个蓝球"
    return None


def tickets_text(tickets: list[Ticket]) -> str:
    return "\n".join(t.text for t in tickets)
