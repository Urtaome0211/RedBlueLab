"""通用数据仓库：加载某个彩种的 CSV，算热号/冷号/遗漏等特征。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import fetch as F
from . import spec as S


@dataclass
class Draw:
    issue: str
    date: str
    week: str
    groups: list[list[int]]
    sales: float | None = None
    pool: float | None = None
    detail: str = ""

    def text(self, spec: S.GameSpec) -> str:
        return S.ticket_text(spec, self.groups)


@dataclass
class Features:
    n: int
    counts: list[dict[int, int]]      # 每个 zone 的号码频次
    omission: list[dict[int, int]]    # 每个 zone 每个号的当前遗漏
    recent: list[dict[int, int]]      # 近 100 期频次


def _parse_groups(spec: S.GameSpec, record: dict) -> list[list[int]]:
    out: list[list[int]] = []
    for zone in spec.zones:
        raw = record.get(zone.label)
        # 注意 0 是合法号码，不能当成空值丢掉
        if raw is None or (isinstance(raw, float) and raw != raw):
            text = ""
        else:
            text = str(raw).strip()
        if zone.ordered and zone.count == 1:
            out.append([int(text)] if text.lstrip("-").isdigit() else [])
        else:
            nums = [int(x) for x in text.split(",") if x.strip().isdigit()]
            out.append(nums)
    return out


class GameStore:
    def __init__(self, key: str, data_dir: Path | None = None):
        self.spec = S.get(key)
        self.data_dir = Path(data_dir or F.DATA_DIR)
        self._df: pd.DataFrame | None = None
        self._features: Features | None = None

    # ---------------------------------------------------------------- 数据
    @property
    def csv_path(self) -> Path:
        return self.data_dir / f"{self.spec.key}_history.csv"

    def available(self) -> bool:
        return self.csv_path.exists()

    def load(self, force: bool = False) -> pd.DataFrame:
        if self._df is None or force:
            df = pd.read_csv(self.csv_path, encoding="utf-8-sig", dtype={"期号": str})
            df = df.sort_values("期号", ascending=False).reset_index(drop=True)
            self._df = df
            self._features = None
        return self._df

    def reload_if_changed(self) -> bool:
        before = self._df is None
        return before or self.load(force=True) is not None

    @property
    def df(self) -> pd.DataFrame:
        return self.load()

    @property
    def count(self) -> int:
        return 0 if not self.available() else len(self.load())

    def latest(self) -> Draw | None:
        if not self.available() or self.df.empty:
            return None
        rec = self.df.iloc[0].to_dict()
        return Draw(issue=str(rec["期号"]), date=str(rec["开奖日期"]), week=str(rec.get("星期") or ""),
                    groups=_parse_groups(self.spec, rec),
                    sales=None if pd.isna(rec.get("销售金额(元)")) else float(rec["销售金额(元)"]),
                    pool=None if pd.isna(rec.get("奖池金额(元)")) else float(rec["奖池金额(元)"]),
                    detail=str(rec.get("详情链接") or ""))

    def recent(self, n: int = 30) -> list[Draw]:
        if not self.available():
            return []
        out: list[Draw] = []
        for rec in self.df.head(n).to_dict("records"):
            out.append(Draw(issue=str(rec["期号"]), date=str(rec["开奖日期"]),
                            week=str(rec.get("星期") or ""),
                            groups=_parse_groups(self.spec, rec)))
        return out

    # ---------------------------------------------------------------- 特征
    def features(self, recent_window: int = 100) -> Features:
        if self._features is not None:
            return self._features
        df = self.load()
        counts: list[dict[int, int]] = []
        omission: list[dict[int, int]] = []
        recent: list[dict[int, int]] = []
        for idx, zone in enumerate(self.spec.zones):
            freq = {n: 0 for n in range(zone.lo, zone.hi + 1)}
            rec = {n: 0 for n in range(zone.lo, zone.hi + 1)}
            for i, row in enumerate(df.to_dict("records")):
                groups = _parse_groups(self.spec, row)
                nums = groups[idx] if idx < len(groups) else []
                for n in nums:
                    freq[n] = freq.get(n, 0) + 1
                    if i < recent_window:
                        rec[n] = rec.get(n, 0) + 1
            miss = {n: len(df) for n in freq}
            for i, row in enumerate(df.to_dict("records")):
                groups = _parse_groups(self.spec, row)
                nums = set(groups[idx] if idx < len(groups) else [])
                for n in nums:
                    if miss[n] == len(df):
                        miss[n] = i
            counts.append(freq)
            omission.append(miss)
            recent.append(rec)
        self._features = Features(n=len(df), counts=counts, omission=omission, recent=recent)
        return self._features

    def summary(self) -> dict:
        df = self.load()
        latest = self.latest()
        return {
            "count": len(df),
            "first": str(df["开奖日期"].iloc[-1]) if len(df) else "",
            "last": str(df["开奖日期"].iloc[0]) if len(df) else "",
            "latest_issue": latest.issue if latest else "",
            "latest_date": latest.date if latest else "",
        }
