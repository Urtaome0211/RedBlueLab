# -*- coding: utf-8 -*-
"""大乐透选号：统计打分 / 约束随机，以及奖金期望估算。"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from itertools import combinations

from . import BACK_COUNT, BACK_MAX, FRONT_COUNT, FRONT_MAX, TOTAL_COMBOS
from .store import DltStore, Features

FRONT_RANGE = list(range(1, FRONT_MAX + 1))
BACK_RANGE = list(range(1, BACK_MAX + 1))

# 固定奖金（元）：三~七等；一、二等为浮动奖，用历史均值
FIXED_MONEY = {3: 5000, 4: 300, 5: 150, 6: 15, 7: 5}

# (前区命中, 后区命中) → 奖级
PRIZE_RULES = {
    (5, 2): 1, (5, 1): 2, (5, 0): 3,
    (4, 2): 4, (4, 1): 5, (3, 2): 6,
    (3, 1): 7, (2, 2): 7, (3, 0): 7, (1, 2): 7, (2, 1): 7, (0, 2): 7,
}

KINDS = [("stats", "统计打分"), ("random", "约束随机")]


@dataclass
class DltParams:
    n_tickets: int = 5
    hot_bias: float = 0.5
    sum_lo: int = 60
    sum_hi: int = 135
    odd_min: int = 1
    odd_max: int = 4
    zone_max: int = 2          # 单个区最多几个号（5 个号分三区）
    max_consecutive: int = 1   # 允许的连号对数上限
    min_span: int = 10
    max_overlap: int = 2       # 注间前区重号上限
    back_mode: str = "balanced"   # balanced / hot / cold / random
    kind: str = "stats"
    seed: int | None = None

    def validate(self) -> None:
        self.n_tickets = max(1, min(20, int(self.n_tickets)))
        self.hot_bias = max(0.0, min(1.0, float(self.hot_bias)))
        lo, hi = int(self.sum_lo), int(self.sum_hi)
        self.sum_lo, self.sum_hi = (lo, hi) if lo <= hi else (hi, lo)
        self.sum_lo = max(15, self.sum_lo)
        self.sum_hi = min(165, self.sum_hi)
        self.odd_min = max(0, min(5, int(self.odd_min)))
        self.odd_max = max(self.odd_min, min(5, int(self.odd_max)))
        self.zone_max = max(1, min(5, int(self.zone_max)))
        self.max_consecutive = max(0, min(4, int(self.max_consecutive)))
        self.min_span = max(4, min(34, int(self.min_span)))
        self.max_overlap = max(0, min(4, int(self.max_overlap)))


@dataclass
class DltTicket:
    front: tuple[int, ...]
    back: tuple[int, ...]
    score: float = 0.0
    reason: str = ""

    @property
    def front_text(self) -> str:
        return " ".join(f"{n:02d}" for n in self.front)

    @property
    def back_text(self) -> str:
        return " ".join(f"{n:02d}" for n in self.back)

    @property
    def text(self) -> str:
        return f"{self.front_text}  +  {self.back_text}"

    @property
    def total(self) -> int:
        return sum(self.front)

    @property
    def span(self) -> int:
        return max(self.front) - min(self.front)

    @property
    def odd(self) -> int:
        return sum(1 for n in self.front if n % 2)

    @property
    def zones(self) -> tuple[int, int, int]:
        z = [0, 0, 0]
        for n in self.front:
            z[0 if n <= 12 else (1 if n <= 24 else 2)] += 1
        return tuple(z)

    @property
    def composition(self) -> str:
        return (f"和值 {self.total} · 奇偶 {self.odd}:{FRONT_COUNT - self.odd}"
                f" · 三区 {self.zones[0]}:{self.zones[1]}:{self.zones[2]}"
                f" · 跨度 {self.span}")


# ---------------------------------------------------------------- 权重
def _z(values: dict[int, float]) -> dict[int, float]:
    vals = list(values.values())
    mean = sum(vals) / len(vals)
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
    return {k: (v - mean) / std for k, v in values.items()}


def front_weights(fs: Features, hot_bias: float) -> dict[int, float]:
    """统计打分：出现次数与近 50 期热度加权，冷号略降权。"""
    count_z = _z(fs.front_count)
    recent_z = _z(fs.front_recent)
    w = {}
    for n in FRONT_RANGE:
        hot = 0.65 * count_z[n] + 0.35 * recent_z[n]
        w[n] = math.exp(hot_bias * hot * 0.8)
    return w


def back_weights(fs: Features, mode: str) -> dict[int, float]:
    if mode == "random":
        return {n: 1.0 for n in BACK_RANGE}
    count_z = _z(fs.back_count)
    omission = fs.back_omission
    if mode == "hot":
        return {n: math.exp(0.9 * count_z[n]) for n in BACK_RANGE}
    if mode == "cold":
        return {n: 1.0 + omission[n] / max(1, fs.n) for n in BACK_RANGE}
    w = {n: math.exp(0.45 * count_z[n]) * (1.0 + 0.6 * omission[n] / max(1, fs.n))
         for n in BACK_RANGE}
    return w


def _consecutive_pairs(nums: list[int]) -> int:
    ordered = sorted(nums)
    return sum(1 for a, b in zip(ordered, ordered[1:]) if b - a == 1)


def _passes(front: tuple[int, ...], p: DltParams) -> bool:
    if not (p.sum_lo <= sum(front) <= p.sum_hi):
        return False
    odd = sum(1 for n in front if n % 2)
    if not (p.odd_min <= odd <= p.odd_max):
        return False
    zones = [sum(1 for n in front if n <= 12),
             sum(1 for n in front if 13 <= n <= 24),
             sum(1 for n in front if n >= 25)]
    if max(zones) > p.zone_max:
        return False
    if _consecutive_pairs(list(front)) > p.max_consecutive:
        return False
    if max(front) - min(front) < p.min_span:
        return False
    return True


def _weighted_front(rng: random.Random, weights: dict[int, float]) -> tuple[int, ...]:
    pool = FRONT_RANGE[:]
    picked: list[int] = []
    for _ in range(FRONT_COUNT):
        total = sum(weights[n] for n in pool)
        r = rng.random() * total
        acc = 0.0
        for n in pool:
            acc += weights[n]
            if acc >= r:
                picked.append(n)
                pool.remove(n)
                break
        else:
            picked.append(pool.pop())
    return tuple(sorted(picked))


def _uniform_front(rng: random.Random) -> tuple[int, ...]:
    return tuple(sorted(rng.sample(FRONT_RANGE, FRONT_COUNT)))


def _weighted_back(rng: random.Random, weights: dict[int, float]) -> tuple[int, ...]:
    pool = BACK_RANGE[:]
    picked: list[int] = []
    for _ in range(BACK_COUNT):
        total = sum(weights[n] for n in pool)
        r = rng.random() * total
        acc = 0.0
        for n in pool:
            acc += weights[n]
            if acc >= r:
                picked.append(n)
                pool.remove(n)
                break
        else:
            picked.append(pool.pop())
    return tuple(sorted(picked))


def _reason(ticket: DltTicket, fs: Features) -> str:
    hot = sorted(FRONT_RANGE, key=lambda n: fs.front_count[n], reverse=True)[:5]
    cold = sorted(FRONT_RANGE, key=lambda n: fs.front_count[n])[:5]
    hits = [n for n in ticket.front if n in hot]
    cold_hits = [n for n in ticket.front if n in cold]
    bits = []
    if hits:
        bits.append("含热号 " + "/".join(f"{n:02d}" for n in hits))
    if cold_hits:
        bits.append("含冷号 " + "/".join(f"{n:02d}" for n in cold_hits))
    if not bits:
        bits.append("热冷均衡")
    if max(ticket.zones) <= 2:
        bits.append("三区分散")
    return "、".join(bits)


# ---------------------------------------------------------------- 推荐
def recommend(store: DltStore, kind: str = "stats",
              params: DltParams | None = None) -> list[DltTicket]:
    p = params or DltParams()
    p.kind = kind
    p.validate()
    rng = random.Random(p.seed)
    fs = store.features()

    fw = front_weights(fs, p.hot_bias) if kind == "stats" else None
    bw = back_weights(fs, p.back_mode) if kind == "stats" else None

    tickets: list[DltTicket] = []
    seen: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()
    attempts = 0
    while len(tickets) < p.n_tickets and attempts < 4000 * p.n_tickets:
        attempts += 1
        front = _weighted_front(rng, fw) if fw else _uniform_front(rng)
        if not _passes(front, p):
            continue
        back = _weighted_back(rng, bw) if bw else tuple(sorted(rng.sample(BACK_RANGE, BACK_COUNT)))
        key = (front, back)
        if key in seen:
            continue
        if any(len(set(front) & set(t.front)) > p.max_overlap for t in tickets):
            continue
        seen.add(key)
        score = (sum(fw[n] for n in front) if fw else 0.0)
        ticket = DltTicket(front=front, back=back, score=round(score, 3))
        ticket.reason = _reason(ticket, fs) if kind == "stats" else ticket.composition
        tickets.append(ticket)

    tickets.sort(key=lambda t: t.score, reverse=True)
    return tickets


# ---------------------------------------------------------------- 期望
def _comb(n: int, k: int) -> int:
    return math.comb(n, k)


def expected_value(store: DltStore) -> dict:
    """按历史平均奖金估算单注（2 元）的期望回报。"""
    df = store.df
    first = df["一等奖单注奖金(元)"].dropna()
    second = df["二等奖单注奖金(元)"].dropna()
    avg1 = float(first.mean()) if len(first) else 7_000_000.0
    avg2 = float(second.mean()) if len(second) else 200_000.0

    money = {1: avg1, 2: avg2}
    money.update(FIXED_MONEY)

    total = 0.0
    by_level: dict[int, float] = {}
    for f in range(0, FRONT_COUNT + 1):
        for b in range(0, BACK_COUNT + 1):
            ways = _comb(FRONT_COUNT, f) * _comb(FRONT_MAX - FRONT_COUNT, FRONT_COUNT - f)
            ways *= _comb(BACK_COUNT, b) * _comb(BACK_MAX - BACK_COUNT, BACK_COUNT - b)
            prob = ways / TOTAL_COMBOS
            level = PRIZE_RULES.get((f, b))
            if level:
                total += prob * money[level]
                by_level[level] = by_level.get(level, 0.0) + prob

    return {
        "combos": TOTAL_COMBOS,
        "avg_first": avg1,
        "avg_second": avg2,
        "ev_per_ticket": total,
        "return_rate": total / 2.0,
        "odds": 1 / (sum(by_level.values()) or 1),
        "by_level": by_level,
    }


def hot_cold(store: DltStore, top: int = 5) -> dict:
    fs = store.features()
    hot_front = sorted(FRONT_RANGE, key=lambda n: fs.front_count[n], reverse=True)[:top]
    cold_front = sorted(FRONT_RANGE, key=lambda n: fs.front_count[n])[:top]
    hot_back = sorted(BACK_RANGE, key=lambda n: fs.back_count[n], reverse=True)[:top]
    cold_back = sorted(BACK_RANGE, key=lambda n: fs.back_count[n])[:top]
    return {
        "hot_front": [(n, fs.front_count[n]) for n in hot_front],
        "cold_front": [(n, fs.front_count[n]) for n in cold_front],
        "hot_back": [(n, fs.back_count[n]) for n in hot_back],
        "cold_back": [(n, fs.back_count[n]) for n in cold_back],
        "omission_front": fs.front_omission,
        "omission_back": fs.back_omission,
    }


def describe_params(p: DltParams, kind: str | None = None) -> str:
    label = dict(KINDS).get(kind or p.kind, "统计打分")
    return (f"{label} · {p.n_tickets} 注 · 和值 {p.sum_lo}-{p.sum_hi}"
            f" · 奇偶 {p.odd_min}-{p.odd_max} · 注间重合≤{p.max_overlap}")
