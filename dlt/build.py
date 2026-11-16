# -*- coding: utf-8 -*-
"""把 data/dlt_raw/page_*.json 解析成结构化数据集，导出 CSV / JSON / Excel。"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from . import BACK_COUNT, BACK_MAX, FRONT_COUNT, FRONT_MAX, GAME_NAME
from .fetch import DEFAULT_DATA_DIR, META_NAME, RAW_DIRNAME

WEEK_CN = "一二三四五六日"
CSV_NAME = "dlt_history.csv"
JSON_NAME = "dlt_history.json"
XLSX_NAME = "dlt_history.xlsx"

# prizeLevelList 里的 sort → 奖级（一级 base，追加档跳过）
PRIZE_SORTS = {101: 1, 301: 2, 501: 3, 601: 4, 701: 5, 801: 6, 901: 7}
PRIZE_NAMES = {1: "一等奖", 2: "二等奖", 3: "三等奖", 4: "四等奖",
               5: "五等奖", 6: "六等奖", 7: "七等奖"}


# ---------------------------------------------------------------- 解析
def full_issue(raw: str) -> str:
    """把 5 位期号 "26130" 补成 7 位 "2026130"（"07001" → "2007001"）。"""
    text = str(raw).strip()
    if len(text) == 5:
        return "20" + text
    return text


def split_date(text: str) -> tuple[str, str]:
    """'2026-11-14' → ('2026-11-14', '六')。"""
    raw = str(text).strip()
    try:
        y, m, d = (int(x) for x in raw.split("-")[:3])
        return raw, WEEK_CN[date(y, m, d).weekday()]
    except (ValueError, IndexError):
        return raw, ""


def parse_money(value) -> int | None:
    """'1,234,567.89' → 1234567；空串/None → None。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in ("-", "--"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_result(text: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    nums = [int(x) for x in str(text).split() if x.strip().isdigit()]
    if len(nums) != FRONT_COUNT + BACK_COUNT:
        raise ValueError(f"号码个数异常：{text}")
    return tuple(nums[:FRONT_COUNT]), tuple(nums[FRONT_COUNT:])


def load_records(raw_dir: Path | None = None) -> tuple[list[dict], dict]:
    root = Path(raw_dir or (DEFAULT_DATA_DIR / RAW_DIRNAME))
    pages = sorted(root.glob("page_*.json"))
    if not pages:
        raise FileNotFoundError(f"未找到分页缓存：{root}")

    by_issue: dict[str, dict] = {}
    for path in pages:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("value", {}).get("list", []):
            issue = full_issue(item.get("lotteryDrawNum", ""))
            if not issue:
                continue
            by_issue[issue] = item       # 后抓的覆盖先抓的

    meta_path = root / META_NAME
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    return list(by_issue.values()), meta


def prize_map(item: dict) -> dict[int, tuple[int | None, int | None]]:
    """{奖级: (注数, 单注奖金)}，跳过「追加」档。"""
    out: dict[int, tuple[int | None, int | None]] = {}
    for row in item.get("prizeLevelList") or []:
        try:
            sort = int(row.get("sort"))
        except (TypeError, ValueError):
            continue
        level = PRIZE_SORTS.get(sort)
        if level is None:
            continue
        count = parse_money(row.get("stakeCount"))
        money = parse_money(row.get("stakeAmount"))
        out[level] = (count, money)
    return out


def build_rows(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        front, back = parse_result(item.get("lotteryDrawResult", ""))
        raw_date, week = split_date(item.get("lotteryDrawTime", ""))
        prizes = prize_map(item)
        first_count, first_money = prizes.get(1, (None, None))
        second_count, second_money = prizes.get(2, (None, None))
        row = {
            "期号": full_issue(item.get("lotteryDrawNum", "")),
            "开奖日期": raw_date,
            "星期": week,
            "前区": ",".join(f"{n:02d}" for n in front),
            "后区": ",".join(f"{n:02d}" for n in back),
        }
        for i, n in enumerate(front, 1):
            row[f"前区{i}"] = n
        for i, n in enumerate(back, 1):
            row[f"后区{i}"] = n

        row.update({
            "销售金额(元)": parse_money(item.get("totalSaleAmount")),
            "奖池金额(元)": parse_money(item.get("poolBalanceAfterdraw")),
            "一等奖注数": first_count,
            "一等奖单注奖金(元)": first_money,
            "二等奖注数": second_count,
            "二等奖单注奖金(元)": second_money,
        })
        for level in (3, 4, 5, 6, 7):
            count, money = prizes.get(level, (None, None))
            row[f"{PRIZE_NAMES[level]}注数"] = count
            row[f"{PRIZE_NAMES[level]}单注奖金(元)"] = money

        row["前区和值"] = sum(front)
        row["跨度"] = max(front) - min(front)
        odd = sum(1 for n in front if n % 2)
        row["奇偶比"] = f"{odd}:{FRONT_COUNT - odd}"
        big = sum(1 for n in front if n >= 18)
        row["大小比"] = f"{big}:{FRONT_COUNT - big}"
        zones = [sum(1 for n in front if lo <= n <= hi)
                 for lo, hi in ((1, 12), (13, 24), (25, 35))]
        row["三区比"] = ":".join(str(z) for z in zones)
        row["详情链接"] = item.get("drawPdfUrl") or ""
        rows.append(row)

    rows.sort(key=lambda r: r["期号"], reverse=True)
    return rows


# ---------------------------------------------------------------- 校验
def validate(df: pd.DataFrame) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"检查项": name, "结果": "通过" if ok else "失败", "说明": detail})

    add("记录数", len(df) > 0, f"{len(df)} 期")
    add("期号唯一", df["期号"].is_unique, f"{df['期号'].nunique()} 个不同期号")

    bad_front = bad_back = 0
    for _, row in df.iterrows():
        front = [int(x) for x in str(row["前区"]).split(",")]
        back = [int(x) for x in str(row["后区"]).split(",")]
        if (len(front) != FRONT_COUNT or len(set(front)) != FRONT_COUNT
                or not all(1 <= n <= FRONT_MAX for n in front)):
            bad_front += 1
        if (len(back) != BACK_COUNT or len(set(back)) != BACK_COUNT
                or not all(1 <= n <= BACK_MAX for n in back)):
            bad_back += 1
    add("前区号码", bad_front == 0, f"{FRONT_COUNT} 个、去重、1–{FRONT_MAX}（异常 {bad_front} 期）")
    add("后区号码", bad_back == 0, f"{BACK_COUNT} 个、去重、1–{BACK_MAX}（异常 {bad_back} 期）")

    dates = pd.to_datetime(df["开奖日期"], errors="coerce")
    add("日期可解析", dates.notna().all(), f"{dates.isna().sum()} 期无法解析")
    desc = dates.reset_index(drop=True)
    add("日期严格倒序", bool((desc.diff().dropna() < pd.Timedelta(0)).all()),
        f"{desc.min().date()} → {desc.max().date()}")

    add("一等奖注数完整", df["一等奖注数"].notna().all(), "每期都有")

    # 空开期没有单注奖金，属正常；只有「有中出却缺奖金」才算异常
    empty_draw = df[df["一等奖注数"].fillna(0) == 0]
    missing_prize = df[df["一等奖单注奖金(元)"].isna()]
    bad = int((missing_prize["一等奖注数"].fillna(0) > 0).sum())
    add("一等奖单注奖金", bad == 0,
        f"{len(missing_prize)} 期缺（均为空开期）" if bad == 0 else f"{bad} 期中出但缺奖金")

    # 这两列是数据源历史上没有，不是解析问题，按「提示」记录
    sales = df["销售金额(元)"]
    first_sales = df.loc[sales.notna(), "期号"].min() if sales.notna().any() else "—"
    checks.append({"检查项": "销售金额覆盖", "结果": "提示",
                   "说明": f"{sales.notna().mean():.1%}（{first_sales} 起官网才提供）"})
    seventh = df["七等奖注数"]
    first_seventh = df.loc[seventh.notna(), "期号"].min() if seventh.notna().any() else "—"
    checks.append({"检查项": "七等奖覆盖", "结果": "提示",
                   "说明": f"{seventh.notna().mean():.1%}（{first_seventh} 起增设七等奖）"})

    # 按年检查期号连续性（同一年内期号应连续）
    gaps: list[str] = []
    for year, group in df.groupby(df["期号"].str[:4]):
        seqs = sorted(int(s[4:]) for s in group["期号"])
        expect = list(range(seqs[0], seqs[-1] + 1))
        missing = sorted(set(expect) - set(seqs))
        if missing:
            gaps.append(f"{year} 缺 {missing[:3]}{'…' if len(missing) > 3 else ''}")
    add("按年期号连续", not gaps, "；".join(gaps) if gaps else "无断号")
    return checks


# ---------------------------------------------------------------- 统计
def frequency_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    front_count: dict[int, int] = {n: 0 for n in range(1, FRONT_MAX + 1)}
    back_count: dict[int, int] = {n: 0 for n in range(1, BACK_MAX + 1)}
    for _, row in df.iterrows():
        for n in str(row["前区"]).split(","):
            front_count[int(n)] += 1
        for n in str(row["后区"]).split(","):
            back_count[int(n)] += 1
    total = len(df)
    front = pd.DataFrame({
        "号码": list(front_count),
        "出现次数": list(front_count.values()),
    })
    front["出现率"] = (front["出现次数"] / total).map(lambda v: f"{v:.1%}")
    back = pd.DataFrame({
        "号码": list(back_count),
        "出现次数": list(back_count.values()),
    })
    back["出现率"] = (back["出现次数"] / total).map(lambda v: f"{v:.1%}")
    return front, back


# ---------------------------------------------------------------- 导出
def export_csv(df: pd.DataFrame, path: Path) -> Path:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def export_json(df: pd.DataFrame, path: Path, meta: dict) -> Path:
    payload = {"game": GAME_NAME, "meta": meta,
               "count": len(df), "records": df.to_dict(orient="records")}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def style_sheet(ws, df: pd.DataFrame, header_fill: str = "00C00000") -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    fill = PatternFill("solid", fgColor=header_fill)
    for idx, column in enumerate(df.columns, 1):
        cell = ws.cell(row=1, column=idx)
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        width = max(9, min(22, max(len(str(column)) * 2 + 2,
                                   int(df[column].astype(str).str.len().max() or 0) + 2)))
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"


def export_xlsx(df: pd.DataFrame, report: list[dict],
                front: pd.DataFrame, back: pd.DataFrame, path: Path) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "开奖记录"
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append([None if pd.isna(v) else v for v in row])
    style_sheet(ws, df)

    for name, data in (("前区频次", front), ("后区频次", back)):
        sheet = wb.create_sheet(name)
        sheet.append(list(data.columns))
        for row in data.itertuples(index=False):
            sheet.append(list(row))
        style_sheet(sheet, data)

    sheet = wb.create_sheet("一等奖明细")
    cols = ["期号", "开奖日期", "一等奖注数", "一等奖单注奖金(元)",
            "二等奖注数", "二等奖单注奖金(元)", "销售金额(元)", "奖池金额(元)"]
    detail = df[[c for c in cols if c in df.columns]]
    sheet.append(list(detail.columns))
    for row in detail.itertuples(index=False):
        sheet.append([None if pd.isna(v) else v for v in row])
    style_sheet(sheet, detail)

    sheet = wb.create_sheet("校验报告")
    rep = pd.DataFrame(report)
    sheet.append(list(rep.columns))
    for row in rep.itertuples(index=False):
        sheet.append(list(row))
    style_sheet(sheet, rep, header_fill="00595959")
    wb.save(path)
    return path


# ---------------------------------------------------------------- 入口
def build(data_dir: str | Path | None = None, export_xlsx_file: bool = True,
          log=None) -> dict:
    root = Path(data_dir or DEFAULT_DATA_DIR)
    log = log or (lambda _m: None)
    items, meta = load_records(root / RAW_DIRNAME)
    log(f"读取 {len(items)} 期原始记录")
    rows = build_rows(items)
    df = pd.DataFrame(rows)
    int_cols = [c for c in df.columns
                if c in ("前区1", "前区2", "前区3", "前区4", "前区5",
                         "后区1", "后区2", "前区和值", "跨度") or "注数" in c
                or c.endswith("(元)")]
    for col in int_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    report = validate(df)
    log("校验：" + "；".join(f"{c['检查项']}={'通过' if c['结果'] == '通过' else '失败'}"
                            for c in report))
    front, back = frequency_tables(df)

    root.mkdir(parents=True, exist_ok=True)
    csv_path = export_csv(df, root / CSV_NAME)
    json_path = export_json(df, root / JSON_NAME, meta)
    xlsx_path = None
    if export_xlsx_file:
        xlsx_path = export_xlsx(df, report, front, back, root / XLSX_NAME)
    log(f"已导出 {csv_path.name} / {json_path.name}"
        + (f" / {xlsx_path.name}" if xlsx_path else ""))
    return {"df": df, "report": report, "front": front, "back": back,
            "csv": csv_path, "json": json_path, "xlsx": xlsx_path, "meta": meta}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="解析大乐透原始数据并导出")
    parser.add_argument("--no-xlsx", action="store_true", help="不导出 Excel")
    args = parser.parse_args(argv)
    res = build(export_xlsx_file=not args.no_xlsx, log=print)
    df = res["df"]
    print(f"\n共 {len(df)} 期：{df['开奖日期'].min()} → {df['开奖日期'].max()}")
    print(df.head(5).to_string(index=False))
    failed = [c for c in res["report"] if c["结果"] == "失败"]
    print("\n校验：" + ("全部通过" if not failed else f"{len(failed)} 项失败"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
