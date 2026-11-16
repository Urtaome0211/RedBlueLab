# -*- coding: utf-8 -*-
"""全组合筛选：把 C(33,6)=1,107,568 注红球组合一次性铺开，按条件过滤。

组合表首次生成约 2~3 秒，之后缓存成 ``<app_root>/cache/combos_u8.npy``（6.6 MB），
再次启动直接 mmap 读取。各条件的指标数组按需计算并缓存，1.1M 行的向量化过滤
通常在 20 ~ 60 ms 内完成，足以做「拖动参数实时显示剩余注数」。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path

import numpy as np

from .. import paths

RED_MAX = 33
BLUE_MAX = 16
TOTAL_COMBOS = 1_107_568
COMBOS_CACHE = "combos_u8.npy"

PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31)

_combos: np.ndarray | None = None
_metrics: dict[str, np.ndarray] = {}


# ---------------------------------------------------------------- 组合表
def combos_path() -> Path:
    return paths.ROOT / "cache" / COMBOS_CACHE


def all_combos(progress=None) -> np.ndarray:
    """(1107568, 6) 的 uint8 组合表，带磁盘缓存。"""
    global _combos
    if _combos is not None:
        return _combos

    cached = combos_path()
    if cached.exists():
        try:
            arr = np.load(cached, mmap_mode="r")
            if arr.shape == (TOTAL_COMBOS, 6):
                _combos = arr
                return arr
        except (OSError, ValueError):
            pass

    if progress:
        progress("首次生成组合表（约 2~3 秒）…")
    arr = np.array(list(combinations(range(1, RED_MAX + 1), 6)), dtype=np.uint8)
    _combos = arr
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        np.save(cached, arr)
    except OSError:
        pass
    return arr


def clear_cache() -> None:
    global _combos, _metrics
    _combos = None
    _metrics = {}
    try:
        combos_path().unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 指标
def _consec_table() -> tuple[np.ndarray, np.ndarray]:
    """5 位间隔掩码 -> (连号对数, 最长连号长度)。"""
    pairs = np.zeros(32, dtype=np.int8)
    longest = np.zeros(32, dtype=np.int8)
    for mask in range(32):
        bits = [(mask >> (4 - i)) & 1 for i in range(5)]
        pairs[mask] = sum(bits)
        run = best = 0
        for b in bits:
            run = run + 1 if b else 0
            best = max(best, run)
        longest[mask] = best + 1 if best else 1
    return pairs, longest


_PAIR_TABLE, _RUN_TABLE = _consec_table()


def _distinct_rows(values: np.ndarray) -> np.ndarray:
    """每行去重后的个数（values 已按行排序）。"""
    if values.shape[1] == 1:
        return np.ones(len(values), dtype=np.int8)
    return (1 + np.diff(values, axis=1) > 0).sum(axis=1).astype(np.int8) + 1


def _ac_values(arr: np.ndarray, step: int = 200_000) -> np.ndarray:
    out = np.empty(len(arr), dtype=np.int16)
    tri = np.triu_indices(6, 1)
    for start in range(0, len(arr), step):
        chunk = arr[start:start + step].astype(np.int16)
        diff = chunk[:, :, None] - chunk[:, None, :]
        pairs = diff[:, tri[0], tri[1]]
        pairs.sort(axis=1)
        distinct = 1 + (np.diff(pairs, axis=1) > 0).sum(axis=1)
        out[start:start + step] = distinct - 5
    return out


def metrics() -> dict[str, np.ndarray]:
    """所有基础指标数组（按需计算，进程内缓存）。"""
    global _metrics
    if _metrics:
        return _metrics
    arr = all_combos()

    diff = arr[:, 1:].astype(np.int16) - arr[:, :-1].astype(np.int16)
    mask5 = np.zeros(len(arr), dtype=np.uint8)
    for i in range(5):
        mask5 |= ((diff[:, i] == 1).astype(np.uint8) << (4 - i))

    total = arr.sum(axis=1).astype(np.int16)
    _metrics = {
        "sum": total,
        "span": (arr[:, -1].astype(np.int16) - arr[:, 0].astype(np.int16)),
        "odd": (arr % 2 == 1).sum(axis=1).astype(np.int8),
        "big": (arr >= 17).sum(axis=1).astype(np.int8),
        "zone1": (arr <= 11).sum(axis=1).astype(np.int8),
        "zone2": ((arr >= 12) & (arr <= 22)).sum(axis=1).astype(np.int8),
        "zone3": (arr >= 23).sum(axis=1).astype(np.int8),
        "consec": _PAIR_TABLE[mask5],
        "run": _RUN_TABLE[mask5],
        "ac": _ac_values(arr),
        "prime": np.isin(arr, np.array(PRIMES, dtype=np.uint8)).sum(axis=1).astype(np.int8),
        "tail": _distinct_rows(np.sort(arr % 10, axis=1)),
        "sum_tail": (total % 10).astype(np.int8),
        "max_num": arr[:, -1].astype(np.int8),
        "min_num": arr[:, 0].astype(np.int8),
    }
    return _metrics


def repeat_count(prev_reds: list[int] | None) -> np.ndarray:
    """与上一期红球的重号个数。"""
    arr = all_combos()
    if not prev_reds:
        return np.zeros(len(arr), dtype=np.int8)
    key = "repeat:" + ",".join(str(int(n)) for n in sorted(prev_reds))
    if key not in _metrics:
        _metrics[key] = np.isin(arr, np.array(sorted(prev_reds), dtype=np.uint8)) \
            .sum(axis=1).astype(np.int8)
    return _metrics[key]


# ---------------------------------------------------------------- 筛选条件
@dataclass
class FilterSpec:
    """所有区间都是 (最小值, 最大值) 或 None（不限）。"""

    sum: tuple[int, int] | None = None
    span: tuple[int, int] | None = None
    odd: tuple[int, int] | None = None
    big: tuple[int, int] | None = None
    zone: tuple[int, int] | None = None          # 三区各自的最小/最大个数
    consec: tuple[int, int] | None = None        # 连号对数 0~5
    ac: tuple[int, int] | None = None            # AC 值 -5 ~ 10
    prime: tuple[int, int] | None = None
    tail: tuple[int, int] | None = None          # 尾数种类数
    repeat: tuple[int, int] | None = None        # 与上期重号个数
    include: tuple[int, ...] = field(default_factory=tuple)
    exclude: tuple[int, ...] = field(default_factory=tuple)
    blue_count: int = 1

    def normalized(self) -> "FilterSpec":
        p = replace(self)
        for name in ("sum", "span", "odd", "big", "zone", "consec", "ac",
                     "prime", "tail", "repeat"):
            value = getattr(p, name)
            if value is None:
                continue
            lo, hi = int(value[0]), int(value[1])
            setattr(p, name, (min(lo, hi), max(lo, hi)))
        p.include = tuple(sorted({int(n) for n in p.include if 1 <= int(n) <= RED_MAX}))
        p.exclude = tuple(sorted({int(n) for n in p.exclude if 1 <= int(n) <= RED_MAX
                                  and int(n) not in p.include}))
        if len(p.include) > 6:
            p.include = p.include[:6]
        p.blue_count = max(0, min(BLUE_MAX, int(p.blue_count)))
        return p


def _range_mask(values: np.ndarray, rng: tuple[int, int] | None) -> np.ndarray | None:
    if rng is None:
        return None
    return (values >= rng[0]) & (values <= rng[1])


def mask(spec: FilterSpec, prev_reds: list[int] | None = None) -> np.ndarray:
    """返回布尔掩码。"""
    spec = spec.normalized()
    m = metrics()
    result = np.ones(TOTAL_COMBOS, dtype=bool)

    for name in ("sum", "span", "odd", "big", "consec", "ac", "prime", "tail"):
        rng = getattr(spec, name)
        part = _range_mask(m[name], rng)
        if part is not None:
            result &= part

    if spec.repeat is not None:
        part = _range_mask(repeat_count(prev_reds), spec.repeat)
        if part is not None:
            result &= part

    if spec.zone is not None:
        lo, hi = spec.zone
        for key in ("zone1", "zone2", "zone3"):
            result &= (m[key] >= lo) & (m[key] <= hi)

    arr = all_combos()
    for n in spec.include:
        result &= (arr == n).any(axis=1)
    for n in spec.exclude:
        result &= ~(arr == n).any(axis=1)
    return result


def count(spec: FilterSpec, prev_reds: list[int] | None = None) -> int:
    return int(mask(spec, prev_reds).sum())


def sample(spec: FilterSpec, n: int, prev_reds: list[int] | None = None,
           seed: int | None = None) -> list[tuple[int, ...]]:
    m = mask(spec, prev_reds)
    idx = np.flatnonzero(m)
    if not len(idx):
        return []
    rng = np.random.default_rng(seed)
    take = idx if len(idx) <= n else rng.choice(idx, size=n, replace=False)
    arr = all_combos()
    return [tuple(int(x) for x in arr[i]) for i in sorted(take)]


def number_frequency(spec: FilterSpec, prev_reds: list[int] | None = None) -> np.ndarray:
    """筛选结果里每个红球的出现次数（下标 1..33）。"""
    arr = all_combos()[mask(spec, prev_reds)]
    if not len(arr):
        return np.zeros(RED_MAX + 1, dtype=int)
    flat = np.asarray(arr).ravel()
    return np.bincount(flat, minlength=RED_MAX + 1).astype(int)


DOMAIN = {"sum": (21, 183), "span": (5, 32), "odd": (0, 6), "big": (0, 6),
          "zone": (0, 6), "consec": (0, 5), "ac": (-5, 10), "prime": (0, 6),
          "tail": (1, 6), "repeat": (0, 6)}


def combinations_text(spec: FilterSpec) -> str:
    """把条件写成一句话（用于复制/记录），完全等于取值范围的条目省略。"""
    spec = spec.normalized()
    names = {"sum": "和值", "span": "跨度", "odd": "奇数", "big": "大号",
             "zone": "每区", "consec": "连号对", "ac": "AC值", "prime": "质数",
             "tail": "尾数种", "repeat": "重号"}
    bits = []
    for key, label in names.items():
        rng = getattr(spec, key)
        if rng is None:
            continue
        lo, hi = DOMAIN[key]
        if rng[0] <= lo and rng[1] >= hi:
            continue
        bits.append(f"{label} {rng[0]}-{rng[1]}")
    if spec.include:
        bits.append("必含 " + " ".join(f"{n:02d}" for n in spec.include))
    if spec.exclude:
        bits.append("排除 " + " ".join(f"{n:02d}" for n in spec.exclude))
    return "；".join(bits) if bits else "不限（全部 1,107,568 注）"
