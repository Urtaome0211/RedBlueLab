"""把抓到的原始 JSON 整理成 CSV / JSON / XLSX 数据集。

列按彩种不同：组合型（七乐彩、快乐8）给号码 + 和值/奇偶/区间，数字型（3D、排列、7星彩）给各位数字。
"""

from __future__ import annotations

import json
import datetime
import re
from pathlib import Path

import pandas as pd

from . import fetch as F
from . import spec as S

WEEK_CN = "一二三四五六日"


def _week(text: str) -> str:
    """开奖日期的星期：福彩接口直接给「2026-11-21(六)」，体彩只给日期，用日期反推。"""
    m = re.search(r"\((\S)\)", text or "")
    if m:
        return m.group(1)
    try:
        day = datetime.date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return ""
    return WEEK_CN[day.weekday()] if day.weekday() < 7 else ""


def _issues(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        issue = row.get("issue") or ""
        if not issue or issue in seen:
            continue
        seen[issue] = row
    return sorted(seen.values(), key=lambda r: r["issue"], reverse=True)


def _combo_stats(nums: list[int], big_line: int, zones: tuple[int, ...]) -> dict:
    total = sum(nums)
    span = max(nums) - min(nums) if nums else 0
    odd = sum(1 for n in nums if n % 2)
    big = sum(1 for n in nums if n >= big_line)
    zone_counts = []
    for lo, hi in zip(zones, zones[1:] + (10 ** 6,)):
        zone_counts.append(sum(1 for n in nums if lo <= n < hi))
    return {"和值": total, "跨度": span, "奇偶比": f"{odd}:{len(nums) - odd}",
            "大小比": f"{big}:{len(nums) - big}", "三区比": ":".join(map(str, zone_counts))}


def _digit_shape(nums: list[int]) -> str:
    if len(set(nums)) == 1:
        return "豹子"
    if len(set(nums)) == 2:
        return "组三"
    if len(set(nums)) == 3:
        return "组六"
    return ""


def build_rows(game: S.GameSpec, rows: list[dict]) -> pd.DataFrame:
    out: list[dict] = []
    for row in _issues(rows):
        groups = row.get("groups") or []
        if any(len(g) != z.count for g, z in zip(groups, game.zones)):
            continue
        item: dict = {"期号": row["issue"], "开奖日期": row.get("date", ""),
                      "星期": _week(row.get("date", ""))}
        for zone, nums in zip(game.zones, groups):
            item[zone.label] = ",".join(f"{n:0{zone.width}d}" for n in nums)
            if zone.count > 1:
                for i, n in enumerate(nums, 1):
                    item[f"{zone.label}{i}"] = n
        if game.key in ("qlc", "kl8"):
            item.update(_combo_stats(groups[0], 16 if game.key == "qlc" else 41,
                                     (1, 11, 21) if game.key == "qlc" else (1, 21, 41, 61)))
            if game.key == "qlc" and len(groups) > 1 and groups[1]:
                item["特别号数字"] = groups[1][0]
        if game.key in ("fc3d", "pl3"):
            nums = [n for g in groups for n in g]
            item["和值"] = sum(nums)
            item["跨度"] = max(nums) - min(nums)
            item["形态"] = _digit_shape(nums)
        if game.key == "pl5":
            nums = [g[0] for g in groups]
            item["和值"] = sum(nums)
            item["奇偶比"] = f"{sum(1 for n in nums if n % 2)}:{sum(1 for n in nums if not n % 2)}"
        if game.key == "qxc":
            nums = [n for g in groups[:-1] for n in g] + list(groups[-1])
            item["和值"] = sum(nums)
            item["奇偶比"] = f"{sum(1 for n in nums if n % 2)}:{sum(1 for n in nums if not n % 2)}"
        item["销售金额(元)"] = row.get("sales")
        item["奖池金额(元)"] = row.get("pool")
        item["详情链接"] = row.get("detail", "")
        out.append(item)
    df = pd.DataFrame(out)
    for col in [c for c in df.columns if c.endswith("(元)")]:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(0).astype("Int64")
    # 只有「单个号码」的列才转整数：合并列（如 7星彩的 前六位）是逗号串，不能转
    single = {z.label for z in game.zones if z.count == 1}
    single |= {f"{z.label}{i}" for z in game.zones for i in range(1, z.count + 1)}
    for col in [c for c in df.columns if c in single]:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(0).astype("Int64")
    return df


# ------------------------------------------------------------------ 奖金
def prize_summary(game: S.GameSpec, rows: list[dict]) -> dict:
    """按奖级统计历史平均单注奖金，供期望值估算。"""
    buckets: dict[str, list[float]] = {}
    for row in _issues(rows):
        for prize in row.get("prizes") or []:
            level = str(prize.get("level") or "")
            cash = prize.get("money") or 0
            if level and cash:
                buckets.setdefault(level, []).append(float(cash))
    levels = {k: round(sum(v) / len(v), 2) for k, v in buckets.items() if v}

    ratios: list[float] = []
    for row in _issues(rows):
        sales = row.get("sales") or 0
        if not sales:
            continue
        payout = sum((p.get("count") or 0) * (p.get("money") or 0) for p in row.get("prizes") or [])
        if payout > 0:
            ratios.append(payout / sales)
    if ratios:
        ratio = sum(ratios) / len(ratios)
        if 0.2 <= ratio <= 0.95:      # 明显离谱的（口径不一致）不采信
            levels["_payout_ratio"] = round(ratio, 4)
            levels["_payout_draws"] = len(ratios)
    return levels


# ------------------------------------------------------------------ 校验
def validate(game: S.GameSpec, df: pd.DataFrame) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"检查项": name, "结果": "通过" if ok else "失败", "说明": detail})

    add("记录数", len(df) > 0, f"{len(df)} 期")
    add("期号唯一", df["期号"].is_unique, "重复率 0" if df["期号"].is_unique else "存在重复期号")
    dates = df["开奖日期"].tolist()
    inversions = sum(1 for i in range(1, len(dates)) if dates[i] > dates[i - 1])
    add("日期倒序", inversions <= max(1, len(dates) // 2000),
        f"{dates[-1]} → {dates[0]}，逆序 {inversions} 处（数据源个别笔误）")
    add("日期完整", df["开奖日期"].str.len().eq(10).all(), "全部为 YYYY-MM-DD")

    bad = 0
    for col, zone in [(z.label, z) for z in game.zones]:
        for text in df[col].dropna():
            nums = [int(x) for x in str(text).split(",") if x.strip().isdigit()]
            if zone.label == "特别号" or not zone.ordered:
                if len(nums) != zone.count or len(set(nums)) != zone.count:
                    bad += 1
                elif any(not (zone.lo <= n <= zone.hi) for n in nums):
                    bad += 1
    add("号码结构", bad == 0, f"异常 {bad} 条" if bad else "位数、范围、去重均正确")

    missing_sales = int(df["销售金额(元)"].isna().sum())
    add("销售金额", True, f"缺失 {missing_sales} 期（{missing_sales / max(len(df), 1) * 100:.1f}%，数据源历史原因）")
    return checks


# ------------------------------------------------------------------ 导出
def style_sheet(ws) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    fill = PatternFill("solid", fgColor="00C00000")
    for cell in ws[1]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"


def export(game: S.GameSpec, df: pd.DataFrame, checks: list[dict],
           freq: dict[str, pd.DataFrame], base: Path | None = None) -> dict:
    base = Path(base or F.DATA_DIR)
    base.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    csv_path = base / f"{game.key}_history.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    paths["csv"] = str(csv_path)

    json_path = base / f"{game.key}_history.json"
    json_path.write_text(df.to_json(orient="records", force_ascii=False, indent=1),
                         encoding="utf-8")
    paths["json"] = str(json_path)

    xlsx_path = base / f"{game.key}_history.xlsx"
    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="开奖记录", index=False)
            for name, table in freq.items():
                table.to_excel(writer, sheet_name=name, index=False)
            pd.DataFrame(checks).to_excel(writer, sheet_name="校验报告", index=False)
        from openpyxl import load_workbook
        wb = load_workbook(xlsx_path)
        for ws in wb.worksheets:
            style_sheet(ws)
        wb.save(xlsx_path)
        paths["xlsx"] = str(xlsx_path)
    except Exception as exc:                            # noqa: BLE001
        paths["xlsx_error"] = repr(exc)
    return paths


def frequency(game: S.GameSpec, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """频次表：组合型统计号码，数字型统计每一位。"""
    tables: dict[str, pd.DataFrame] = {}
    if game.key in ("qlc", "kl8"):
        counter: dict[int, int] = {}
        for text in df[game.zones[0].label]:
            for n in str(text).split(","):
                if n.strip().isdigit():
                    counter[int(n)] = counter.get(int(n), 0) + 1
        zone = game.zones[0]
        rows = [{"号码": f"{n:0{zone.width}d}", "出现次数": counter.get(n, 0)}
                for n in range(zone.lo, zone.hi + 1)]
        tables["号码频次"] = pd.DataFrame(rows)
        if game.key == "qlc" and "特别号" in df.columns:
            blue = df["特别号"].value_counts().sort_index()
            tables["特别号频次"] = pd.DataFrame(
                [{"号码": k, "出现次数": int(v)} for k, v in blue.items()])
    else:
        for zone in game.zones:
            if not zone.ordered and zone.count == 1:
                counts = df[zone.label].value_counts().sort_index()
                tables[f"{zone.label}频次"] = pd.DataFrame(
                    [{"号码": int(k), "出现次数": int(v)} for k, v in counts.items()])
            else:
                col = f"{zone.label}1"
                if col in df.columns:
                    counts = df[col].value_counts().sort_index()
                    tables[f"{zone.label}频次"] = pd.DataFrame(
                        [{"号码": int(k), "出现次数": int(v)} for k, v in counts.items()])
    return tables


def build(game: S.GameSpec, base: Path | None = None, log=None) -> dict:
    base = Path(base or F.DATA_DIR)
    rows = F.read_pages(game, base)
    if not rows:
        raise RuntimeError(f"{game.name}：没有原始数据，请先抓取")
    df = build_rows(game, rows)
    checks = validate(game, df)
    freq = frequency(game, df)
    paths = export(game, df, checks, freq, base)
    prizes = prize_summary(game, rows)
    prize_path = base / f"{game.key}_prizes.json"
    prize_path.write_text(json.dumps(prizes, ensure_ascii=False, indent=1), encoding="utf-8")
    if log:
        failed = [c for c in checks if c["结果"] == "失败"]
        log(f"{game.name}：{len(df)} 期，校验 {len(checks) - len(failed)}/{len(checks)} 通过")
    return {"game": game.key, "df": df, "checks": checks, "freq": freq,
            "paths": paths, "prizes": prizes}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="从原始 JSON 构建数据集")
    parser.add_argument("game", nargs="?", default="all")
    args = parser.parse_args(argv)
    games = S.GAMES if args.game == "all" else (S.get(args.game),)
    for game in games:
        try:
            result = build(game, log=print)
        except RuntimeError as exc:
            print(f"跳过 {game.key}：{exc}")
            continue
        for key, path in result["paths"].items():
            print(f"  {game.key} {key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
