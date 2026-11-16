# -*- coding: utf-8 -*-
"""解析原始 JSON → 结构化数据集（CSV / JSON / Excel）+ 完整性校验。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .. import paths

PRIZE_NAMES = {1: "一等奖", 2: "二等奖", 3: "三等奖", 4: "四等奖", 5: "五等奖",
               6: "六等奖", 7: "七等奖"}

Log = Callable[[str], None]


def load_records(raw_dir: Path) -> list[dict]:
    """合并所有分页，按期号去重（保留首次出现）。"""
    seen: dict[str, dict] = {}
    pages = sorted(raw_dir.glob("page_*.json"))
    if not pages:
        raise FileNotFoundError("未找到原始数据，请先抓取开奖数据")
    for p in pages:
        data = json.loads(p.read_text(encoding="utf-8"))
        for it in data.get("result") or []:
            seen.setdefault(str(it["code"]), it)
    return [seen[k] for k in sorted(seen, reverse=True)]


def split_date(raw: str) -> tuple[str, str]:
    """'2026-10-25(日)' -> ('2026-10-25', '日')"""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\s*[（(]?([^)）]*)", raw or "")
    if not m:
        return raw or "", ""
    return m.group(1), m.group(2).strip()


def to_int(v) -> int | None:
    try:
        s = str(v).strip()
        return int(float(s)) if s not in ("", "None", "nan") else None
    except (TypeError, ValueError):
        return None


def parse_money(v) -> tuple[int | None, str]:
    """奖金字段可能是 '5490089（含派奖172413）' 这种带注释的字符串。

    返回 (金额整数, 注释文本)。注释通常是派奖/加奖说明。
    """
    if v is None:
        return None, ""
    s = str(v).strip()
    if not s:
        return None, ""
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", s)
    if not m:
        return None, s
    note = m.group(2).strip().strip("（）()").strip()
    return int(float(m.group(1))), note


def build_rows(records: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    rows, raw_out = [], []
    for it in records:
        date, week = split_date(it.get("date", ""))
        reds = [int(x) for x in str(it.get("red", "")).split(",") if x.strip()]
        blues = [x for x in str(it.get("blue", "")).split(",") if x.strip()]
        blue = int(blues[0]) if blues else None

        grades = {}
        for g in it.get("prizegrades") or []:
            t = to_int(g.get("type"))
            if t is None:
                continue
            money, note = parse_money(g.get("typemoney"))
            grades[t] = (to_int(g.get("typenum")), money, note)

        row = {
            "期号": str(it.get("code")),
            "开奖日期": date,
            "星期": week,
            "红球": ",".join(f"{n:02d}" for n in reds),
            "蓝球": blue,
        }
        for i in range(1, 7):
            row[f"红球{i}"] = reds[i - 1] if len(reds) >= i else None
        row["销售金额(元)"] = to_int(it.get("sales"))
        row["奖池金额(元)"] = to_int(it.get("poolmoney"))
        for t in range(1, 7):
            cnt, money, note = grades.get(t, (None, None, ""))
            row[f"{PRIZE_NAMES[t]}注数"] = cnt
            row[f"{PRIZE_NAMES[t]}单注奖金(元)"] = money
            if t == 1:
                row["一等奖派奖说明"] = note
        if reds:
            row["红球和值"] = sum(reds)
            row["跨度"] = max(reds) - min(reds)
            odd = sum(1 for n in reds if n % 2 == 1)
            row["奇偶比"] = f"{odd}:{6 - odd}"
            big = sum(1 for n in reds if n >= 17)
            row["大小比"] = f"{big}:{6 - big}"
            zones = (sum(1 for n in reds if n <= 11),
                     sum(1 for n in reds if 12 <= n <= 22),
                     sum(1 for n in reds if n >= 23))
            row["三区比"] = ":".join(str(z) for z in zones)
        row["中奖地区"] = (it.get("content") or "").strip()
        row["详情链接"] = ("https://www.cwl.gov.cn" + it["detailsLink"]) if it.get("detailsLink") else ""
        rows.append(row)

        raw_out.append({
            "code": str(it.get("code")), "date": date, "week": week,
            "red": reds, "blue": blue, "sales": to_int(it.get("sales")),
            "poolmoney": to_int(it.get("poolmoney")),
            "prizegrades": it.get("prizegrades") or [],
            "content": it.get("content", ""),
            "detailsLink": it.get("detailsLink", ""),
            "videoLink": it.get("videoLink", ""),
        })
    return pd.DataFrame(rows), raw_out


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """逐条校验并返回校验报告。"""
    checks = []
    n = len(df)
    checks.append(("记录数", f"{n} 期"))

    dup = df["期号"].duplicated().sum()
    checks.append(("期号唯一性", "通过（无重复）" if dup == 0 else f"失败：{dup} 条重复"))

    date_ok = pd.to_datetime(df["开奖日期"], errors="coerce").notna().sum()
    checks.append(("日期可解析", f"{date_ok}/{n}"))

    red_ok = df["红球"].str.fullmatch(r"\d{2}(,\d{2}){5}").sum()
    checks.append(("红球格式（6 个两位号码）", f"{red_ok}/{n}"))

    rng_ok = 0
    for _, r in df.iterrows():
        reds = [int(x) for x in r["红球"].split(",")]
        if (len(set(reds)) == 6 and all(1 <= x <= 33 for x in reds)
                and isinstance(r["蓝球"], (int, float)) and 1 <= int(r["蓝球"]) <= 16):
            rng_ok += 1
    checks.append(("号码取值范围/去重", f"{rng_ok}/{n}"))

    d = pd.to_datetime(df["开奖日期"], errors="coerce")
    checks.append(("日期倒序排列", "通过" if d.is_monotonic_decreasing else "不严格（存在同日/乱序）"))

    gaps = []
    for year, grp in df.groupby(df["期号"].str[:4]):
        nums = sorted(int(c[4:]) for c in grp["期号"])
        expect = list(range(1, nums[-1] + 1))
        if nums != expect:
            missing = sorted(set(expect) - set(nums))
            gaps.append(f"{year} 缺 {missing[:10]}{'…' if len(missing) > 10 else ''}")
    checks.append(("期号连续性（按年）", "连续，无断号" if not gaps else "；".join(gaps)))

    checks.append(("时间范围", f"{df['开奖日期'].min()} ~ {df['开奖日期'].max()}"))

    for col in ["一等奖注数", "一等奖单注奖金(元)", "销售金额(元)", "奖池金额(元)"]:
        filled = df[col].notna().sum()
        checks.append((f"{col} 完整率", f"{filled}/{n} ({filled / n:.1%})"))

    return pd.DataFrame(checks, columns=["校验项", "结果"])


def frequency_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    red_cnt = {i: 0 for i in range(1, 34)}
    blue_cnt = {i: 0 for i in range(1, 17)}
    red_last = {i: "" for i in range(1, 34)}
    blue_last = {i: "" for i in range(1, 17)}
    reds_list, blues_list, dates = [], [], []
    for _, r in df.iterrows():
        reds = [int(v) for v in r["红球"].split(",")]
        reds_list.append(reds)
        blues_list.append(int(r["蓝球"]))
        dates.append(r["开奖日期"])
        for x in reds:
            red_cnt[x] += 1
            if not red_last[x]:
                red_last[x] = r["开奖日期"]
        b = int(r["蓝球"])
        blue_cnt[b] += 1
        if not blue_last[b]:
            blue_last[b] = r["开奖日期"]

    def omission(target: int, seq: list, is_red: bool) -> int:
        for i, (v, dt) in enumerate(zip(seq, dates)):
            hit = target in v if is_red else v == target
            if hit:
                return i
        return len(seq)

    n = len(df)
    total_red = sum(red_cnt.values())
    red = pd.DataFrame([{
        "红球号码": f"{k:02d}", "出现次数": v,
        "出现频率": v / total_red if total_red else 0,
        "理论频率": 6 / 33,
        "最近一次出现": red_last[k],
        "当前遗漏(期)": omission(k, reds_list, True),
    } for k, v in red_cnt.items()]).sort_values("出现次数", ascending=False)

    total_blue = sum(blue_cnt.values())
    blue = pd.DataFrame([{
        "蓝球号码": f"{k:02d}", "出现次数": v,
        "出现频率": v / total_blue if total_blue else 0,
        "理论频率": 1 / 16,
        "最近一次出现": blue_last[k],
        "当前遗漏(期)": omission(k, blues_list, False),
    } for k, v in blue_cnt.items()]).sort_values("出现次数", ascending=False)
    _ = n
    return red, blue


def style_sheet(ws, freeze: str = "A2", widths: dict | None = None) -> None:
    header_fill = PatternFill("solid", fgColor="C00000")
    thin = Side(style="thin", color="D9D9D9")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = freeze
    ws.row_dimensions[1].height = 24
    for col in ws.iter_cols(min_row=1, max_row=ws.max_row):
        letter = get_column_letter(col[0].column)
        header = str(col[0].value or "")
        if widths and header in widths:
            ws.column_dimensions[letter].width = widths[header]
        elif header in ("期号", "开奖日期", "星期", "蓝球"):
            ws.column_dimensions[letter].width = 12
        elif "奖金" in header or "金额" in header:
            ws.column_dimensions[letter].width = 15
        else:
            ws.column_dimensions[letter].width = 11
    if ws.max_row > 1:
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            for cell in row:
                cell.border = Border(bottom=thin)
                if isinstance(cell.value, (int, float)) and "金额" in str(ws.cell(1, cell.column).value):
                    cell.number_format = "#,##0"


def build(data_dir: Path | str | None = None, export_xlsx: bool = True,
          log: Log | None = None) -> dict:
    """重建数据集并返回结果（df / 校验报告 / 频次表 / 输出路径）。"""
    log = log or (lambda msg: None)
    data_dir = Path(data_dir or paths.DATA_DIR)
    raw_dir = data_dir / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)

    records = load_records(raw_dir)
    df, raw = build_rows(records)
    report = validate(df)
    red_freq, blue_freq = frequency_tables(df)

    csv_path = data_dir / "ssq_history.csv"
    json_path = data_dir / "ssq_history.json"
    xlsx_path = data_dir / "ssq_history.xlsx"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps({
        "source": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/",
        "api": "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice",
        "count": len(raw),
        "date_range": [df["开奖日期"].min(), df["开奖日期"].max()],
        "records": raw,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if export_xlsx:
        long_cols = [c for c in df.columns if c != "详情链接"]
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            df[long_cols].to_excel(writer, sheet_name="开奖记录", index=False)
            df[["期号", "开奖日期", "一等奖注数", "一等奖单注奖金(元)", "一等奖派奖说明",
                "二等奖注数", "二等奖单注奖金(元)", "销售金额(元)", "奖池金额(元)", "中奖地区", "详情链接"]
               ].to_excel(writer, sheet_name="一等奖明细", index=False)
            red_freq.to_excel(writer, sheet_name="红球频次", index=False)
            blue_freq.to_excel(writer, sheet_name="蓝球频次", index=False)
            report.to_excel(writer, sheet_name="校验报告", index=False)

            wb = writer.book
            for name in ("开奖记录", "一等奖明细", "红球频次", "蓝球频次", "校验报告"):
                style_sheet(wb[name])
            for name in ("红球频次", "蓝球频次"):
                ws = wb[name]
                for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                    for cell in row:
                        if isinstance(cell.value, float) and cell.value < 1.01:
                            cell.number_format = "0.00%"
            rep = wb["校验报告"]
            rep.column_dimensions["A"].width = 26
            rep.column_dimensions["B"].width = 60

    log(f"{len(df)} 期，{df['开奖日期'].min()} ~ {df['开奖日期'].max()}")
    return {"df": df, "report": report, "red_freq": red_freq, "blue_freq": blue_freq,
            "csv": csv_path, "json": json_path, "xlsx": xlsx_path if export_xlsx else None}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="解析原始数据并导出数据集")
    ap.add_argument("--no-xlsx", action="store_true", help="跳过 Excel 导出")
    args = ap.parse_args(argv)

    res = build(export_xlsx=not args.no_xlsx, log=print)
    print(res["report"].to_string(index=False))
    print(f"\n已输出：\n  {res['csv']}\n  {res['json']}")
    if res["xlsx"]:
        print(f"  {res['xlsx']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
