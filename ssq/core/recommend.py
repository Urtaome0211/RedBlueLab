# -*- coding: utf-8 -*-
"""号码推荐引擎。

两套策略，界面可切换：

1. ``stats``（统计打分）：用全量历史算红球/蓝球的「频次 + 近期热度 + 遗漏」混合分值，
   按分值加权抽样生成候选注，再按注级得分排序、做注间去重后取前 N 注。
   分值是**历史统计的加权组合**，权重可调；它不代表未来概率。
2. ``random``（约束随机）：号码均匀随机，只保留「和值 / 奇偶 / 三区 / 跨度 / 连号」
   落在历史常见区间内的组合，注间去重。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

import numpy as np

from .store import BLUE_MAX, RED_MAX, DataStore, Features

RED_RANGE = np.arange(1, RED_MAX + 1)


@dataclass
class RecParams:
    n_tickets: int = 5
    hot_bias: float = 0.5          # 0 = 偏冷号回补，1 = 偏热号延续
    sum_lo: int = 80
    sum_hi: int = 130
    odd_min: int = 2
    odd_max: int = 4
    zone_min: int = 1
    zone_max: int = 4
    max_consecutive: int = 1
    min_span: int = 15
    max_overlap: int = 2
    blue_mode: str = "balanced"    # balanced / hot / cold / random
    kind: str = "stats"            # stats / random（界面记住上次选择）
    seed: int | None = None

    def validate(self) -> "RecParams":
        p = replace(self)
        p.n_tickets = max(1, min(20, int(p.n_tickets)))
        p.hot_bias = float(min(1.0, max(0.0, p.hot_bias)))
        p.sum_lo, p.sum_hi = int(p.sum_lo), int(p.sum_hi)
        if p.sum_lo > p.sum_hi:
            p.sum_lo, p.sum_hi = p.sum_hi, p.sum_lo
        p.odd_min = max(0, min(6, int(p.odd_min)))
        p.odd_max = max(p.odd_min, min(6, int(p.odd_max)))
        p.zone_min = max(0, min(6, int(p.zone_min)))
        p.zone_max = max(p.zone_min, min(6, int(p.zone_max)))
        p.max_consecutive = max(0, min(3, int(p.max_consecutive)))
        p.min_span = max(0, min(32, int(p.min_span)))
        p.max_overlap = max(0, min(5, int(p.max_overlap)))
        if p.blue_mode not in ("balanced", "hot", "cold", "random"):
            p.blue_mode = "balanced"
        return p


@dataclass
class Ticket:
    reds: tuple[int, ...]
    blue: int
    score: float = 0.0
    reason: str = ""

    @property
    def red_text(self) -> str:
        return " ".join(f"{n:02d}" for n in self.reds)

    @property
    def blue_text(self) -> str:
        return f"{self.blue:02d}"

    @property
    def text(self) -> str:
        return f"{self.red_text} + {self.blue_text}"

    @property
    def total(self) -> int:
        return sum(self.reds)

    @property
    def span(self) -> int:
        return max(self.reds) - min(self.reds)

    @property
    def odd(self) -> int:
        return sum(1 for n in self.reds if n % 2 == 1)

    @property
    def even(self) -> int:
        return 6 - self.odd

    @property
    def zones(self) -> tuple[int, int, int]:
        return (sum(1 for n in self.reds if n <= 11),
                sum(1 for n in self.reds if 12 <= n <= 22),
                sum(1 for n in self.reds if n >= 23))

    @property
    def zone_text(self) -> str:
        return ":".join(str(z) for z in self.zones)

    @property
    def composition(self) -> str:
        return (f"和值 {self.total} · 奇偶 {self.odd}:{self.even} · "
                f"三区 {self.zone_text} · 跨度 {self.span}")


# ---------------------------------------------------------------- 特征权重
def _zscore(v: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """对指定下标区间做标准化；全零时返回全零。"""
    out = np.zeros_like(v, dtype=float)
    vals = v[mask]
    std = float(vals.std())
    if std < 1e-9:
        return out
    out[mask] = (vals - float(vals.mean())) / std
    return out


def red_weights(fs: Features, hot_bias: float) -> np.ndarray:
    """红球抽样权重（长度 34，下标 0 占位）。"""
    mask = np.zeros(RED_MAX + 1, dtype=bool)
    mask[1:] = True
    z_count = _zscore(fs.red_count, mask)
    z_recent = _zscore(fs.red_recent, mask)
    z_om = _zscore(fs.red_omission, mask)

    hot = 0.65 * z_count + 0.35 * z_recent
    due = z_om
    mix = hot_bias * hot + (1.0 - hot_bias) * due
    mix[0] = -np.inf
    mix = np.clip(mix, -4, 4)
    w = np.exp(1.0 * mix)
    w[0] = 0.0
    return w / w.sum()


def blue_weights(fs: Features, mode: str) -> np.ndarray:
    mask = np.zeros(BLUE_MAX + 1, dtype=bool)
    mask[1:] = True
    if mode == "random" or fs.n == 0:
        w = np.zeros(BLUE_MAX + 1)
        w[1:] = 1.0
        return w / w.sum()

    z_count = _zscore(fs.blue_count, mask)
    z_recent = _zscore(fs.blue_recent, mask)
    z_om = _zscore(fs.blue_omission, mask)
    if mode == "hot":
        mix = 0.7 * z_count + 0.3 * z_recent
    elif mode == "cold":
        mix = z_om
    else:
        mix = 0.4 * (0.6 * z_count + 0.4 * z_recent) + 0.6 * z_om
    mix = np.clip(mix, -4, 4)
    w = np.exp(1.0 * mix)
    w[0] = 0.0
    return w / w.sum()


# ---------------------------------------------------------------- 约束
def _passes(reds: np.ndarray, p: RecParams) -> bool:
    s = int(reds.sum())
    if s < p.sum_lo or s > p.sum_hi:
        return False
    odd = int(np.count_nonzero(reds % 2))
    if odd < p.odd_min or odd > p.odd_max:
        return False
    z1 = int(np.count_nonzero(reds <= 11))
    z2 = int(np.count_nonzero((reds >= 12) & (reds <= 22)))
    z3 = 6 - z1 - z2
    if min(z1, z2, z3) < p.zone_min or max(z1, z2, z3) > p.zone_max:
        return False
    if int(np.count_nonzero(np.diff(reds) == 1)) > p.max_consecutive:
        return False
    if int(reds.max() - reds.min()) < p.min_span:
        return False
    return True


def _reason(reds: tuple[int, ...], blue: int, p: RecParams, fs: Features,
            hot_ids: list[int], cold_ids: list[int]) -> str:
    t = Ticket(reds, blue)
    bits = [t.composition]
    hit_hot = [n for n in reds if n in hot_ids][:2]
    hit_cold = [n for n in reds if n in cold_ids][:2]
    if p.hot_bias >= 0.65 and hit_hot:
        bits.append("含热号 " + "/".join(f"{n:02d}" for n in hit_hot))
    elif p.hot_bias <= 0.35 and hit_cold:
        bits.append("含冷号 " + "/".join(f"{n:02d}" for n in hit_cold))
    elif hit_hot:
        bits.append("含热号 " + "/".join(f"{n:02d}" for n in hit_hot))
    elif hit_cold:
        bits.append("含冷号 " + "/".join(f"{n:02d}" for n in hit_cold))
    else:
        bits.append("未含前 5 热号，分散度较高")
    return "；".join(bits)


# ---------------------------------------------------------------- 主流程
def _generate(store: DataStore, p: RecParams, kind: str,
              pool_target: int) -> list[tuple[np.ndarray, int, float]]:
    fs = store.features()
    rng = np.random.default_rng(p.seed)
    rw = red_weights(fs, p.hot_bias) if kind == "stats" else np.full(RED_MAX + 1, 1 / RED_MAX)
    bw = blue_weights(fs, p.blue_mode) if kind == "stats" else np.full(BLUE_MAX + 1, 1 / BLUE_MAX)
    rw[0] = 0.0
    bw[0] = 0.0

    red_mix = np.log(np.maximum(rw, 1e-12))
    blue_mix = np.log(np.maximum(bw, 1e-12))

    out: list[tuple[np.ndarray, int, float]] = []
    attempts = 0
    max_attempts = max(4000, pool_target * 60)
    while len(out) < pool_target and attempts < max_attempts:
        attempts += 1
        reds = np.sort(rng.choice(RED_RANGE, size=6, replace=False, p=rw[1:]))
        if not _passes(reds, p):
            continue
        blue = int(rng.choice(np.arange(1, BLUE_MAX + 1), p=bw[1:]))
        score = float(red_mix[reds].sum() + 0.35 * blue_mix[blue])
        out.append((reds, blue, score))
    return out


def recommend(store: DataStore, kind: str = "stats",
              params: RecParams | None = None) -> list[Ticket]:
    """生成推荐注。kind: 'stats' | 'random'。"""
    p = (params or RecParams()).validate()
    if not store.available:
        raise RuntimeError("没有可用的历史数据")

    pool = _generate(store, p, kind, pool_target=max(600, p.n_tickets * 120))
    if not pool:
        raise RuntimeError("在当前约束下没有生成符合条件的组合，请放宽参数")

    if kind == "random":
        rng = np.random.default_rng(p.seed)
        order = rng.permutation(len(pool))
        ranked = [pool[i] for i in order]
    else:
        ranked = sorted(pool, key=lambda item: item[2], reverse=True)

    fs = store.features()
    counts = fs.red_count
    hot_ids = [int(i) for i in np.argsort(-counts[1:])[:8] + 1]
    cold_ids = [int(i) for i in np.argsort(counts[1:])[:8] + 1]

    chosen: list[tuple[np.ndarray, int, float]] = []
    used_blues: set[int] = set()
    for strict_overlap in (True, False):
        for reds, blue, score in ranked:
            if len(chosen) >= p.n_tickets:
                break
            rset = set(int(x) for x in reds)
            if any(len(rset & set(int(x) for x in c[0])) > p.max_overlap for c in chosen):
                if strict_overlap:
                    continue
            if blue in used_blues and len(used_blues) < BLUE_MAX:
                if strict_overlap:
                    continue
            chosen.append((reds, blue, score))
            used_blues.add(blue)
        if len(chosen) >= p.n_tickets:
            break

    if not chosen:
        reds, blue, score = ranked[0]
        chosen = [(reds, blue, score)]

    tickets: list[Ticket] = []
    for reds, blue, score in chosen[:p.n_tickets]:
        t_reds = tuple(int(x) for x in reds)
        if kind == "stats":
            reason = _reason(t_reds, blue, p, fs, hot_ids, cold_ids)
        else:
            reason = Ticket(t_reds, blue).composition
        tickets.append(Ticket(t_reds, blue, round(score, 3), reason))
    return tickets


# ---------------------------------------------------------------- 其它统计
def expected_value(store: DataStore) -> dict:
    """按历史奖金均值估算单注期望回报（含各奖级概率）。"""
    total_comb = 17_721_088
    counts = {1: 1, 2: 15, 3: 162, 4: 7695, 5: 137_475, 6: 1_043_640}
    fixed = {3: 3000, 4: 200, 5: 10, 6: 5}

    avg1 = avg2 = 0.0
    if store.available:
        df = store.df
        m1 = df.loc[df["一等奖单注奖金(元)"].notna(), "一等奖单注奖金(元)"]
        m2 = df.loc[df["二等奖单注奖金(元)"].notna(), "二等奖单注奖金(元)"]
        avg1 = float(m1.mean()) if len(m1) else 7_000_000.0
        avg2 = float(m2.mean()) if len(m2) else 200_000.0
    else:
        avg1, avg2 = 7_000_000.0, 200_000.0

    per_draw = (counts[1] * avg1 + counts[2] * avg2
                + sum(counts[k] * fixed[k] for k in (3, 4, 5, 6)))
    ev = per_draw / total_comb
    return {"avg_first": avg1, "avg_second": avg2, "ev_per_ticket": ev,
            "return_rate": ev / 2.0, "combinations": total_comb}


def hot_cold(store: DataStore, top: int = 5) -> dict:
    """冷热号列表（按出现次数）。"""
    fs = store.features()
    reds = [(i, int(fs.red_count[i])) for i in range(1, RED_MAX + 1)]
    blues = [(i, int(fs.blue_count[i])) for i in range(1, BLUE_MAX + 1)]
    reds.sort(key=lambda x: x[1], reverse=True)
    blues.sort(key=lambda x: x[1], reverse=True)
    return {
        "red_hot": reds[:top], "red_cold": reds[-top:][::-1],
        "blue_hot": blues[:top], "blue_cold": blues[-top:][::-1],
        "red_omission": [(i, int(fs.red_omission[i])) for i in
                         sorted(range(1, RED_MAX + 1), key=lambda i: -fs.red_omission[i])[:top]],
    }


def _popcount(mask: int) -> int:
    """位掩码里的 1 的个数（numpy 有新接口就用，老版本退回内置实现）。"""
    fn = getattr(np, "bitwise_count", None)
    if fn is not None:
        return int(fn(mask))
    return bin(int(mask)).count("1")


def _popcount_arr(values: np.ndarray) -> np.ndarray:
    """数组版本的 popcount。"""
    fn = getattr(np, "bitwise_count", None)
    if fn is not None:
        return fn(values)
    raw = np.ascontiguousarray(values).view(np.uint8).reshape(values.shape + (8,))
    return np.unpackbits(raw, axis=-1).sum(axis=-1)


def _mask_of(reds: tuple[int, ...]) -> int:
    out = 0
    for n in reds:
        out |= 1 << (int(n) - 1)
    return out


def _pool_combo_masks(pool: list[int]) -> np.ndarray:
    """池内所有 C(n,6) 组合的位掩码。"""
    from itertools import combinations

    return np.array([_mask_of(c) for c in combinations(pool, 6)], dtype=np.uint64)


def _evaluate(tmask: np.ndarray, combo_masks: np.ndarray) -> tuple[int, float, float]:
    """(最差命中, 平均命中, 最差命中占比)。tmask 为各注位掩码。"""
    hits = _popcount_arr(combo_masks[:, None] & tmask[None, :])
    best = hits.max(axis=1)
    floor = int(best.min())
    share = float((best <= floor).sum()) / float(len(best))
    return floor, float(best.mean()), share


def _score(value: tuple[int, float, float]) -> tuple[int, float, float]:
    """排序用：先看保底，再看「只中保底」的组合占比（越低越好），最后看平均。"""
    return value[0], -value[2], value[1]


# ---------------------------------------------------------------- 覆盖优化
def coverage_pool(store: DataStore, pool_size: int) -> list[int]:
    """选出一个「号码池」：按权重排序，同时保证三区各有代表。"""
    fs = store.features()
    pool_size = max(12, min(20, int(pool_size)))
    w = red_weights(fs, 0.5)
    order = [int(i) for i in np.argsort(-w[1:]) + 1]

    quota = [max(2, round(pool_size / 3))] * 3
    pool: list[int] = []
    for zi, (lo, hi) in enumerate(((1, 11), (12, 22), (23, 33))):
        picks = [n for n in order if lo <= n <= hi][:quota[zi]]
        pool.extend(picks)

    for n in order:
        if len(pool) >= pool_size:
            break
        if n not in pool:
            pool.append(n)
    return sorted(pool[:pool_size])


def _hit_floor(tickets: list[tuple[int, ...]], pool: list[int]
               ) -> tuple[int, float, int, np.ndarray, float]:
    """池内全中时的最差命中数（覆盖下限）、平均命中数、组合数、组合掩码、最差占比。"""
    total = 1
    for i in range(6):
        total = total * (len(pool) - i) // (i + 1)

    combo_masks = _pool_combo_masks(pool)
    tmask = np.array([_mask_of(t) for t in tickets], dtype=np.uint64)
    floor, avg, share = _evaluate(tmask, combo_masks)
    return floor, avg, total, combo_masks, share


def _refine_coverage(tickets: list[tuple[int, ...]], pool: list[int],
                     params: RecParams, rng: np.random.Generator,
                     combo_masks: np.ndarray) -> tuple[list[tuple[int, ...]], int, float, float]:
    """局部搜索：每次换掉一注里的一个号码，只接受「保底更高（或同保底但更均匀）」的改动。"""
    best = [tuple(t) for t in tickets]
    tmask = np.array([_mask_of(t) for t in best], dtype=np.uint64)
    cur = _evaluate(tmask, combo_masks)
    pool_arr = np.array(pool)
    iters = max(150, min(600, 2400 // max(1, len(best))))

    for _ in range(iters):
        i = int(rng.integers(len(best)))
        pos = int(rng.integers(6))
        old = best[i]
        new = int(pool_arr[int(rng.integers(len(pool)))])
        if new in old:
            continue
        cand = list(old)
        cand[pos] = new
        cand.sort()
        reds = np.array(cand)
        if not _passes(reds, params):
            continue
        trial = tmask.copy()
        trial[i] = _mask_of(tuple(cand))
        value = _evaluate(trial, combo_masks)
        if _score(value) > _score(cur):
            best[i] = tuple(int(x) for x in cand)
            tmask = trial
            cur = value
    return best, cur[0], cur[1], cur[2]


def recommend_coverage(store: DataStore, params: RecParams | None = None,
                       pool_size: int = 18) -> tuple[list[Ticket], dict]:
    """覆盖优化：把 N 注铺开在号码池上，最大化「池内全中时的保底命中」。"""
    p = (params or RecParams()).validate()
    if not store.available:
        raise RuntimeError("没有可用的历史数据")

    fs = store.features()
    pool = coverage_pool(store, pool_size)
    rng = np.random.default_rng(p.seed)
    w = red_weights(fs, p.hot_bias)
    probs = np.array([w[n] for n in pool], dtype=float)
    probs = probs / probs.sum()

    candidates: list[tuple[int, ...]] = []
    attempts = 0
    while len(candidates) < 4000 and attempts < 60_000:
        attempts += 1
        idx = rng.choice(len(pool), size=6, replace=False, p=probs)
        reds = np.sort(np.array([pool[i] for i in idx]))
        if _passes(reds, p):
            candidates.append(tuple(int(x) for x in reds))
    if not candidates:
        raise RuntimeError("号码池太窄，生成不出符合约束的组合，试试增大池子或放宽条件")

    overlap_limit = max(p.max_overlap, 3)
    chosen: list[tuple[int, ...]] = []
    covered: set[int] = set()
    while len(chosen) < p.n_tickets:
        best = None
        best_key = (-1, -1.0)
        for reds in candidates:
            rset = set(reds)
            if reds in chosen:
                continue
            if any(len(rset & set(c)) > overlap_limit for c in chosen):
                continue
            gain = len(rset - covered)
            key = (gain, float(w[list(reds)].sum()))
            if key > best_key:
                best_key, best = key, reds
        if best is None:
            break
        chosen.append(best)
        covered |= set(best)

    if not chosen:
        raise RuntimeError("覆盖优化没有选出组合，请放宽参数")

    _floor, _avg, total, combo_masks, _share = _hit_floor(chosen, pool)
    chosen, floor, avg_hit, worst_share = _refine_coverage(chosen, pool, p, rng, combo_masks)
    covered = set().union(*(set(t) for t in chosen)) if chosen else set()

    bw = blue_weights(fs, p.blue_mode)
    blue_order = [int(i) for i in np.argsort(-bw[1:]) + 1]

    tickets: list[Ticket] = []
    for i, reds in enumerate(chosen):
        blue = blue_order[i % min(len(blue_order), p.n_tickets)] if p.blue_mode != "random" \
            else int(rng.integers(1, BLUE_MAX + 1))
        reason = (f"覆盖包 {len(pool)} 个号；池内 6 个全中时最差也中 {floor} 红"
                  f"（平均 {avg_hit:.1f} 红，{worst_share:.0%} 的组合只中 {floor} 红）")
        tickets.append(Ticket(reds, blue, round(float(w[list(reds)].sum()), 3), reason))

    info = {"pool": pool, "floor": floor, "avg_hit": avg_hit,
            "pool_combos": total, "covered": len(covered), "worst_share": worst_share}
    return tickets, info


def describe_params(p: RecParams, kind: str) -> str:
    algo = {"stats": "统计打分", "random": "约束随机", "coverage": "覆盖优化"}.get(kind, kind)
    return (f"{algo} · {p.n_tickets} 注 · 和值 {p.sum_lo}-{p.sum_hi} · "
            f"奇偶 {p.odd_min}-{p.odd_max} · 注间重合≤{p.max_overlap}")


def iter_text(tickets: Iterable[Ticket]) -> str:
    return "\n".join(t.text for t in tickets)
