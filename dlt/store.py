# -*- coding: utf-8 -*-
"""读取大乐透数据集，提供开奖记录与统计特征。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import BACK_COUNT, BACK_MAX, FRONT_COUNT, FRONT_MAX
from .build import CSV_NAME, JSON_NAME

DEFAULT_DATA_DIR = Path("data")


def _as_int(value) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Draw:
    issue: str
    date: str
    week: str
    front: tuple[int, ...]
    back: tuple[int, ...]
    sales: int | None = None
    pool: int | None = None
    first_count: int | None = None
    first_money: int | None = None
    second_count: int | None = None
    second_money: int | None = None
    content: str = ""

    @property
    def front_text(self) -> str:
        return " ".join(f"{n:02d}" for n in self.front)

    @property
    def back_text(self) -> str:
        return " ".join(f"{n:02d}" for n in self.back)


@dataclass
class Features:
    n: int
    front_count: dict[int, int]
    back_count: dict[int, int]
    front_omission: dict[int, int]
    back_omission: dict[int, int]
    front_recent: dict[int, int]
    back_recent: dict[int, int]
    mean_sum: float = 0.0
    std_sum: float = 0.0


def _omission(draws: list[tuple[int, ...]], size: int) -> dict[int, int]:
    """每个号码距离最近一次出现的期数（0 = 最新一期就出了）。"""
    out = {n: len(draws) for n in range(1, size + 1)}
    for idx, draw in enumerate(reversed(draws)):
        for n in draw:
            if out[n] == len(draws):
                out[n] = idx
    return out


def _recent_count(asc: list, recent: int, size: int) -> dict[int, int]:
    counts = {n: 0 for n in range(1, size + 1)}
    for draw in asc[-recent:]:
        for n in draw:
            counts[n] += 1
    return counts


class DltStore:
    """大乐透数据仓库。`df` 按期号倒序，`asc` 为升序 Draw 列表。"""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self._df: pd.DataFrame | None = None
        self._asc: list[Draw] | None = None
        self._features: Features | None = None

    # ------------------------------------------------ 基础
    @property
    def csv_path(self) -> Path:
        return self.data_dir / CSV_NAME

    @property
    def available(self) -> bool:
        return self.csv_path.exists()

    def load(self, force: bool = False) -> "DltStore":
        if self._df is not None and not force:
            return self
        if not self.available:
            self._df = pd.DataFrame()
            self._asc = []
            self._features = None
            return self
        df = pd.read_csv(self.csv_path, encoding="utf-8-sig", dtype={"期号": str})
        df["期号"] = df["期号"].astype(str)
        df = df.sort_values("期号", ascending=False).reset_index(drop=True)
        self._df = df
        try:
            self._mtime = self.csv_path.stat().st_mtime
        except OSError:
            self._mtime = None
        self._asc = None
        self._features = None
        return self

    def reload_if_changed(self) -> bool:
        if self._df is None:
            self.load()
            return True
        try:
            mtime = self.csv_path.stat().st_mtime
        except OSError:
            return False
        if getattr(self, "_mtime", None) == mtime:
            return False
        self._mtime = mtime
        self.load(force=True)
        return True

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self.load()
        return self._df if self._df is not None else pd.DataFrame()

    @property
    def count(self) -> int:
        return len(self.df)

    @property
    def asc(self) -> list[Draw]:
        if self._asc is None:
            draws: list[Draw] = []
            for rec in self.df.to_dict("records"):
                front = tuple(int(rec[f"前区{i}"]) for i in range(1, FRONT_COUNT + 1))
                back = tuple(int(rec[f"后区{i}"]) for i in range(1, BACK_COUNT + 1))
                draws.append(Draw(
                    issue=str(rec.get("期号", "")),
                    date=str(rec.get("开奖日期", "")),
                    week=str(rec.get("星期", "")),
                    front=front, back=back,
                    sales=_as_int(rec.get("销售金额(元)")),
                    pool=_as_int(rec.get("奖池金额(元)")),
                    first_count=_as_int(rec.get("一等奖注数")),
                    first_money=_as_int(rec.get("一等奖单注奖金(元)")),
                    second_count=_as_int(rec.get("二等奖注数")),
                    second_money=_as_int(rec.get("二等奖单注奖金(元)")),
                    content=str(rec.get("详情链接", "") or ""),
                ))
            self._asc = sorted(draws, key=lambda d: d.issue)
        return self._asc

    def latest(self) -> Draw | None:
        return self.asc[-1] if self.asc else None

    def recent(self, n: int = 10) -> list[Draw]:
        return list(reversed(self.asc[-n:]))

    def issues(self) -> list[str]:
        return [d.issue for d in self.asc]

    # ------------------------------------------------ 特征
    def features(self) -> Features:
        if self._features is not None:
            return self._features
        asc = self.asc
        fronts = [d.front for d in asc]
        backs = [d.back for d in asc]
        sums = [sum(f) for f in fronts]
        mean = sum(sums) / len(sums) if sums else 0.0
        var = sum((s - mean) ** 2 for s in sums) / len(sums) if sums else 0.0
        self._features = Features(
            n=len(asc),
            front_count=_recent_count(fronts, len(fronts), FRONT_MAX),
            back_count=_recent_count(backs, len(backs), BACK_MAX),
            front_omission=_omission(fronts, FRONT_MAX),
            back_omission=_omission(backs, BACK_MAX),
            front_recent=_recent_count(fronts, 50, FRONT_MAX),
            back_recent=_recent_count(backs, 50, BACK_MAX),
            mean_sum=mean, std_sum=var ** 0.5,
        )
        return self._features

    def summary(self) -> dict:
        df = self.df
        if df.empty:
            return {"count": 0, "first": "-", "last": "-", "updated": "-"}
        try:
            updated = pd.Timestamp(self.csv_path.stat().st_mtime, unit="s", tz="Asia/Shanghai")
            updated_text = updated.strftime("%Y-%m-%d %H:%M")
        except OSError:
            updated_text = "-"
        return {
            "count": len(df),
            "first": str(df["开奖日期"].iloc[-1]),
            "last": str(df["开奖日期"].iloc[0]),
            "updated": updated_text,
        }
