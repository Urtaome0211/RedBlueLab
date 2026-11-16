# -*- coding: utf-8 -*-
"""数据集内存视图：读取 CSV，提供统计特征与最近开奖。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .. import paths

RED_MAX = 33
BLUE_MAX = 16


@dataclass(frozen=True)
class Draw:
    issue: str
    date: str
    week: str
    reds: tuple[int, ...]
    blue: int
    sales: int | None = None
    pool: int | None = None
    first_count: int | None = None
    first_money: int | None = None
    content: str = ""

    @property
    def red_text(self) -> str:
        return " ".join(f"{n:02d}" for n in self.reds)


@dataclass
class Features:
    """在「按期升序」数组上算出来的频次/遗漏特征。"""
    n: int
    red_count: np.ndarray      # 下标 1..33
    red_omission: np.ndarray   # 距最近一次出现的期数（0 = 上一期刚开）
    blue_count: np.ndarray     # 下标 1..16
    blue_omission: np.ndarray
    red_recent: np.ndarray     # 最近 50 期出现次数
    blue_recent: np.ndarray
    sums: np.ndarray
    spans: np.ndarray
    odds: np.ndarray

    @property
    def mean_sum(self) -> float:
        return float(self.sums.mean()) if self.n else 0.0

    @property
    def std_sum(self) -> float:
        return float(self.sums.std()) if self.n else 0.0


class DataStore:
    """对 data/ssq_history.csv 的只读封装，带 mtime 失效检测。"""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir or paths.DATA_DIR)
        self.csv_path = self.data_dir / "ssq_history.csv"
        self._mtime: float = -1.0
        self._df: pd.DataFrame | None = None
        self._asc: pd.DataFrame | None = None
        self._features: Features | None = None
        self.load(force=True)

    # ---------------- 载入 ----------------
    @property
    def available(self) -> bool:
        return self._df is not None and len(self._df) > 0

    def load(self, force: bool = False) -> bool:
        if not self.csv_path.exists():
            self._df = self._asc = None
            self._features = None
            return False
        mtime = self.csv_path.stat().st_mtime
        if not force and self._df is not None and abs(mtime - self._mtime) < 1e-6:
            return True
        df = pd.read_csv(self.csv_path, encoding="utf-8-sig", dtype={"期号": str})
        df["蓝球"] = pd.to_numeric(df["蓝球"], errors="coerce").astype("Int64")
        df = df[df["蓝球"].notna()].reset_index(drop=True)
        asc = df.sort_values("开奖日期", kind="stable").reset_index(drop=True)
        self._df, self._asc = df, asc
        self._mtime = mtime
        self._features = None
        return True

    def reload_if_changed(self) -> bool:
        """文件被外部改动（例如命令行重建）时重新载入。"""
        if not self.csv_path.exists():
            return False
        if self._mtime < 0:
            return self.load(force=True)
        return self.load()

    # ---------------- 基本查询 ----------------
    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            raise FileNotFoundError(f"未找到数据集：{self.csv_path}")
        return self._df

    @property
    def asc(self) -> pd.DataFrame:
        if self._asc is None:
            raise FileNotFoundError(f"未找到数据集：{self.csv_path}")
        return self._asc

    @property
    def count(self) -> int:
        return 0 if self._df is None else len(self._df)

    @property
    def updated_at(self) -> str:
        if not self.csv_path.exists():
            return "-"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.csv_path.stat().st_mtime))

    def latest(self) -> Draw | None:
        if not self.available:
            return None
        r = self._df.iloc[0]
        return self._to_draw(r)

    def recent(self, n: int = 100) -> pd.DataFrame:
        return self.df.head(n)

    def issues(self) -> list[str]:
        return [] if not self.available else self.df["期号"].tolist()

    @staticmethod
    def _to_draw(r: pd.Series) -> Draw:
        reds = tuple(int(x) for x in str(r["红球"]).split(","))
        return Draw(
            issue=str(r["期号"]), date=str(r["开奖日期"]), week=str(r.get("星期", "")),
            reds=reds, blue=int(r["蓝球"]),
            sales=_opt_int(r.get("销售金额(元)")), pool=_opt_int(r.get("奖池金额(元)")),
            first_count=_opt_int(r.get("一等奖注数")),
            first_money=_opt_int(r.get("一等奖单注奖金(元)")),
            content=str(r.get("中奖地区", "") or ""),
        )

    # ---------------- 特征 ----------------
    def red_array(self) -> np.ndarray:
        asc = self.asc
        return np.array([[int(x) for x in s.split(",")] for s in asc["红球"]],
                        dtype=np.int16).reshape(-1, 6)

    def blue_array(self) -> np.ndarray:
        return self.asc["蓝球"].astype(int).to_numpy(dtype=np.int16)

    def features(self) -> Features:
        if self._features is not None:
            return self._features
        if not self.available:
            z = np.zeros(RED_MAX + 1)
            return Features(0, z, z.copy(), np.zeros(BLUE_MAX + 1),
                            np.zeros(BLUE_MAX + 1), z.copy(), np.zeros(BLUE_MAX + 1),
                            np.array([]), np.array([]), np.array([]))

        reds = self.red_array()
        blues = self.blue_array()
        n = len(reds)

        red_count = np.bincount(reds.ravel(), minlength=RED_MAX + 1).astype(float)
        blue_count = np.bincount(blues, minlength=BLUE_MAX + 1).astype(float)

        red_om = np.full(RED_MAX + 1, float(n))
        blue_om = np.full(BLUE_MAX + 1, float(n))
        for i in range(n - 1, -1, -1):
            for v in reds[i]:
                if red_om[v] == n:
                    red_om[v] = n - 1 - i
            b = blues[i]
            if blue_om[b] == n:
                blue_om[b] = n - 1 - i

        k = min(50, n)
        red_recent = np.bincount(reds[-k:].ravel(), minlength=RED_MAX + 1).astype(float)
        blue_recent = np.bincount(blues[-k:], minlength=BLUE_MAX + 1).astype(float)

        sums = reds.sum(axis=1).astype(float)
        spans = (reds.max(axis=1) - reds.min(axis=1)).astype(float)
        odds = (reds % 2 == 1).sum(axis=1).astype(float)

        self._features = Features(n, red_count, red_om, blue_count, blue_om,
                                  red_recent, blue_recent, sums, spans, odds)
        return self._features

    def summary(self) -> dict:
        if not self.available:
            return {"count": 0, "first": "-", "last": "-", "updated": "-"}
        return {"count": self.count,
                "first": str(self.df["开奖日期"].iloc[-1]),
                "last": str(self.df["开奖日期"].iloc[0]),
                "updated": self.updated_at}


def _opt_int(v) -> int | None:
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None
