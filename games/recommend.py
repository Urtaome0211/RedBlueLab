"""通用推荐：组合型（七乐彩/快乐8）与数字型（3D/排列/7星彩）。"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from . import fetch as F
from . import spec as S
from .store import GameStore


@dataclass
class RecParams:
    n_tickets: int = 5
    hot_bias: float = 0.5
    sum_lo: int | None = None
    sum_hi: int | None = None
    odd_min: int | None = None
    odd_max: int | None = None
    max_overlap: int = 2
    kind: str = "stats"
    seed: int | None = None


@dataclass
class Ticket:
    groups: list[list[int]]
    score: float = 0.0
    reason: str = ""

    def text(self, spec: S.GameSpec) -> str:
        return S.ticket_text(spec, self.groups)

    def composition(self, spec: S.GameSpec) -> str:
        nums = [n for g in self.groups for n in g]
        if spec.zones[0].ordered:
            odd = sum(1 for n in nums if n % 2)
            text = f"和值 {sum(nums)}、奇偶 {odd}:{len(nums) - odd}"
            if spec.key in ("fc3d", "pl3") and len(set(nums)) < 3:
                text += "、形态 " + ("豹子" if len(set(nums)) == 1 else "组三")
            return text
        odd = sum(1 for n in nums if n % 2)
        return f"和值 {sum(nums)}、奇偶 {odd}:{len(nums) - odd}"


# ------------------------------------------------------------------ 权重
def _zscore(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    mean = sum(values.values()) / len(values)
    var = sum((v - mean) ** 2 for v in values.values()) / len(values)
    std = math.sqrt(var) or 1.0
    return {k: (v - mean) / std for k, v in values.items()}


def _softmax(scores: dict[int, float], temperature: float = 1.0) -> dict[int, float]:
    keys = sorted(scores)
    if not keys:
        return {}
    top = max(scores[k] for k in keys)
    exps = {k: math.exp((scores[k] - top) / max(temperature, 0.05)) for k in keys}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def zone_weights(store: GameStore, index: int, hot_bias: float = 0.5) -> dict[int, float]:
    fs = store.features()
    zone = store.spec.zones[index]
    counts = fs.counts[index]
    recent = fs.recent[index]
    omission = fs.omission[index]
    zc, zr, zo = _zscore(counts), _zscore(recent), _zscore(omission)
    bias = max(0.0, min(1.0, hot_bias))
    score = {}
    for n in range(zone.lo, zone.hi + 1):
        hot = 0.7 * zc.get(n, 0.0) + 0.3 * zr.get(n, 0.0)
        due = zo.get(n, 0.0)
        score[n] = (hot * bias) + (due * (1 - bias))
    # 位数型彩种每个位置只有 10 个候选，太尖的分布会让每注都是同一批数字
    return _softmax(score, temperature=2.2 if zone.ordered else 0.9)


def _weighted_sample(rng: random.Random, weights: dict[int, float], k: int) -> list[int]:
    pool = dict(weights)
    picked: list[int] = []
    for _ in range(k):
        if not pool:
            break
        total = sum(pool.values())
        r = rng.random() * total
        acc = 0.0
        for num, w in pool.items():
            acc += w
            if acc >= r:
                picked.append(num)
                del pool[num]
                break
        else:
            picked.append(next(iter(pool)))
            pool.pop(picked[-1])
    return sorted(picked)


# ------------------------------------------------------------------ 约束
def _default_range(store: GameStore, index: int = 0) -> tuple[int, int]:
    """用历史分位数给一个默认和值区间。"""
    df = store.df
    zone = store.spec.zones[0]
    sums = []
    if store.spec.zones[0].ordered or store.spec.key in ("qlc", "kl8"):
        if "和值" in df.columns:
            sums = [int(v) for v in df["和值"].dropna().tolist()]
    if not sums:
        if zone.ordered and store.spec.zones[0].count == 1:
            nums = df[zone.label].dropna().tolist()
            n = store.spec.ticket_count()
            sums = [int(v) * 0 for v in nums]
    if len(sums) < 20:
        return 0, 10 ** 6
    sums.sort()
    lo, hi = sums[int(len(sums) * 0.12)], sums[int(len(sums) * 0.88)]
    # 快乐8 一期开 20 个号，但推荐的是「选十」的 10 个号，和值要按比例折算
    zone = store.spec.zones[0]
    if zone.count > store.spec.ticket[0] and not zone.ordered:
        factor = store.spec.ticket[0] / zone.count
        lo, hi = int(lo * factor), int(hi * factor)
    return lo, hi


def _passes(spec: S.GameSpec, groups: list[list[int]], params: RecParams) -> bool:
    nums = [n for g in groups for n in g]
    if len(nums) < spec.ticket_count():
        return False
    total = sum(nums)
    if params.sum_lo is not None and total < params.sum_lo:
        return False
    if params.sum_hi is not None and total > params.sum_hi:
        return False
    if params.odd_min is not None or params.odd_max is not None:
        odd = sum(1 for n in nums if n % 2)
        if params.odd_min is not None and odd < params.odd_min:
            return False
        if params.odd_max is not None and odd > params.odd_max:
            return False
    if spec.key in ("fc3d", "pl3") and len(set(nums)) == 1:
        return False
    if spec.key == "qlc":
        basics = groups[0]
        zones = (sum(1 for n in basics if n <= 10), sum(1 for n in basics if 11 <= n <= 20),
                 sum(1 for n in basics if n >= 21))
        if max(zones) > 4:
            return False
    if spec.key == "kl8":
        zones = (sum(1 for n in nums if n <= 20), sum(1 for n in nums if 21 <= n <= 40),
                 sum(1 for n in nums if 41 <= n <= 60), sum(1 for n in nums if n >= 61))
        if max(zones) > 5:
            return False
    return True


def _overlap(a: Ticket, b: Ticket, spec: S.GameSpec) -> int:
    if spec.zones[0].ordered:
        return sum(1 for x, y in zip(a.groups[0], b.groups[0]) if x == y)
    return len(set(a.groups[0]) & set(b.groups[0]))


# ------------------------------------------------------------------ 生成
def _signature(spec: S.GameSpec, ticket: Ticket) -> tuple:
    return tuple(tuple(g) for g in ticket.groups)


def _reason(spec: S.GameSpec, ticket: Ticket, store: GameStore) -> str:
    fs = store.features()
    nums_all = [n for g in ticket.groups for n in g]
    odd = sum(1 for n in nums_all if n % 2)
    if spec.zones[0].ordered:
        # 号码形态已经在 composition 里说了，这里不再重复
        return f"按频次与遗漏加权抽取" if spec.key == "qxc" else ""
    nums = [n for g in ticket.groups for n in g]
    top = sorted(fs.counts[0].items(), key=lambda kv: -kv[1])[:5]
    hot = [n for n, _ in top if n in nums]
    cold = sorted(fs.counts[0].items(), key=lambda kv: kv[1])[:3]
    cold_hit = [n for n, _ in cold if n in nums]
    width = store.spec.zones[0].width
    bits = []
    if hot:
        bits.append("含热号 " + "、".join(f"{n:0{width}d}" for n in hot[:3]))
    if cold_hit:
        bits.append("含冷号 " + "、".join(f"{n:0{width}d}" for n in cold_hit[:2]))
    nums_all = nums
    if spec.key == "kl8":
        z = [sum(1 for n in nums_all if n <= 20), sum(1 for n in nums_all if 21 <= n <= 40),
             sum(1 for n in nums_all if 41 <= n <= 60), sum(1 for n in nums_all if n >= 61)]
        bits.append("四区 " + ":".join(map(str, z)))
    elif spec.key == "qlc":
        z = [sum(1 for n in nums_all if n <= 10), sum(1 for n in nums_all if 11 <= n <= 20),
             sum(1 for n in nums_all if n >= 21)]
        bits.append("三区 " + ":".join(map(str, z)))
    if not bits:
        bits.append("冷热均衡")
    return "、".join(bits)


def recommend(store: GameStore, kind: str = "stats", params: RecParams | None = None) -> list[Ticket]:
    spec = store.spec
    params = params or RecParams()
    rng = random.Random(params.seed)
    fs = store.features()
    if params.sum_lo is None or params.sum_hi is None:
        lo, hi = _default_range(store)
        params = RecParams(**{**params.__dict__,
                              "sum_lo": params.sum_lo if params.sum_lo is not None else lo,
                              "sum_hi": params.sum_hi if params.sum_hi is not None else hi})
    if params.odd_min is None and not spec.zones[0].ordered:
        n = spec.ticket_count()
        params = RecParams(**{**params.__dict__, "odd_min": max(0, n // 2 - 1),
                              "odd_max": n // 2 + 1})

    tickets: list[Ticket] = []
    attempts = 0
    while len(tickets) < params.n_tickets and attempts < 4000:
        attempts += 1
        groups: list[list[int]] = []
        for index, zone in enumerate(spec.zones):
            count = spec.ticket[index]
            if count == 0:
                groups.append([])
                continue
            weights = zone_weights(store, index, params.hot_bias)
            if kind == "random":
                picked = rng.sample(list(weights), min(count, len(weights)))
                groups.append(sorted(picked))
            elif zone.ordered:
                # 有序位：每一位独立按该位的历史分布抽（7 星彩第 7 位是 0-14）
                nums = list(weights)
                probs = [weights[n] for n in nums]
                groups.append([rng.choices(nums, weights=probs, k=1)[0] for _ in range(count)])
            else:
                groups.append(_weighted_sample(rng, weights, count))
        if not _passes(spec, groups, params):
            continue
        ticket = Ticket(groups)
        if any(_signature(spec, ticket) == _signature(spec, t) for t in tickets):
            continue
        if any(_overlap(ticket, t, spec) > params.max_overlap for t in tickets):
            continue
        ticket.reason = _reason(spec, ticket, store) if kind == "stats" else "随机均匀抽样"
        tickets.append(ticket)
    for i, ticket in enumerate(tickets):
        ticket.score = round(-float(i), 2)
    return tickets


# ------------------------------------------------------------------ 冷热
def hot_cold(store: GameStore, top: int = 5) -> dict:
    fs = store.features()
    zone = store.spec.zones[0]
    counts = fs.counts[0]
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    cold = sorted(counts.items(), key=lambda kv: kv[1])
    return {"hot": ordered[:top], "cold": cold[:top],
            "hot_miss": [(n, fs.omission[0].get(n, 0)) for n, _ in cold[:top]]}


# ------------------------------------------------------------------ 期望值
def _prizes(store: GameStore) -> dict:
    path = store.data_dir / f"{store.spec.key}_prizes.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def _comb(n: int, k: int) -> int:
    return math.comb(n, k) if 0 <= k <= n else 0


def _ev_rows(store: GameStore) -> list[dict]:
    spec = store.spec
    prizes = _prizes(store)
    rows: list[dict] = []

    def add(level: str, prob: float, money: float, note: str = "") -> None:
        rows.append({"奖项": level, "概率": prob, "单注奖金": money, "说明": note})

    if spec.key == "kl8":
        total = _comb(80, 10)
        table = {10: 5_000_000, 9: 8_000, 8: 720, 7: 80, 6: 5, 5: 3, 0: 2}
        for m, money in table.items():
            prob = _comb(20, m) * _comb(60, 10 - m) / total
            avg = prizes.get(f"x10z{m}") or money
            add(f"猜中 {m} 个", prob, max(avg, money) if m >= 9 else avg, "浮动" if m >= 9 else "固定")
    elif spec.key == "qlc":
        total = _comb(30, 7)
        table = [
            ("一等奖", "1", _comb(7, 7) * 1),
            ("二等奖", "2", _comb(7, 6) * 1),
            ("三等奖", "3", _comb(7, 6) * 22),
            ("四等奖", "4", _comb(7, 5) * 22),
            ("五等奖", "5", _comb(7, 5) * _comb(22, 2)),
            ("六等奖", "6", _comb(7, 4) * _comb(22, 2)),
            ("七等奖", "7", _comb(7, 4) * _comb(22, 3)),
        ]
        fallback = {"1": 1_000_000, "2": 25_000, "3": 2_610, "4": 200, "5": 50, "6": 10, "7": 5}
        for level, key, combos in table:
            add(level, combos / total, prizes.get(key) or fallback[key],
                "浮动" if key in ("1", "2") else "固定/均值")
    elif spec.key in ("fc3d", "pl3"):
        # 只算直选：组选三/六是另外的投注方式，不是同一注的额外奖级
        add("直选", 1 / 1000, 1040, "固定（组选三 346、组选六 173 为其他玩法）")
    elif spec.key == "pl5":
        add("直选", 1 / 100_000, 100_000, "固定")
    elif spec.key == "qxc":
        total = 10 ** 6 * 15
        add("一等奖", 1 / total, prizes.get("一等奖") or 5_000_000, "浮动")
        add("二等奖", 1 / 10 ** 6, prizes.get("二等奖") or 30_000, "浮动")
        add("三等奖", (6 * 9) / total, 3_000, "固定（前 6 位中 5 + 第 7 位）")
        add("四等奖", (6 * 9 * 10) / total, 500, "固定")
        add("五等奖", (15 * 9 * 10) / total, 30, "固定")
        add("六等奖", (15 * 9 * 10 * 5) / total, 5, "固定")
    return rows


def expected_value(store: GameStore) -> dict:
    """单注 2 元的期望回报与返还率。

    浮动奖金（一、二等奖等）用「历史派奖总额 / 历史销售额」反推更可靠，
    奖级表只作为逐项拆解展示。
    """
    rows = _ev_rows(store)
    any_prize = sum(r["概率"] for r in rows)
    prizes = _prizes(store)
    ratio = prizes.get("_payout_ratio")
    if ratio:
        return {"rows": rows, "ev_per_ticket": round(2 * ratio, 3),
                "return_rate": round(float(ratio), 4), "any_prize": round(any_prize, 8),
                "combos": _combos(store.spec), "basis": "历史派奖率"}
    ev = sum(r["概率"] * r["单注奖金"] for r in rows)
    return {"rows": rows, "ev_per_ticket": round(ev, 3), "return_rate": round(ev / 2, 4),
            "any_prize": round(any_prize, 8), "combos": _combos(store.spec), "basis": "奖级估算"}


def _combos(spec: S.GameSpec) -> int:
    total = 1
    for zone, count in zip(spec.zones, spec.ticket):
        if count == 0:
            continue
        if zone.ordered:
            total *= zone.size ** count
        else:
            total *= _comb(zone.size, count)
    return total


def describe_params(params: RecParams, kind: str) -> str:
    bits = ["统计打分" if kind == "stats" else "约束随机", f"{params.n_tickets} 注"]
    if params.sum_lo is not None and params.sum_hi is not None:
        bits.append(f"和值 {params.sum_lo}-{params.sum_hi}")
    if params.odd_min is not None and params.odd_max is not None:
        bits.append(f"奇偶 {params.odd_min}-{params.odd_max}")
    bits.append(f"注间重合≤{params.max_overlap}")
    return " · ".join(bits)
