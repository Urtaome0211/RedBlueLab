# -*- coding: utf-8 -*-
"""抓取超级大乐透历史开奖（体彩官网公开接口）。

接口：``https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry``
必带 ``gameNo=85``（超级大乐透）、``isVerify=1``，返回 JSON：
``value.total`` 总期数、``value.list`` 每期含 ``lotteryDrawNum``（5 位期号）、
``lotteryDrawResult``（"01 07 11 27 29 02 06"，前 5 个前区 + 2 个后区）、
``totalSaleAmount``、``poolBalanceAfterdraw``、``prizeLevelList``。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import GAME_NAME

BASE_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
REFERER = "https://www.lottery.gov.cn/"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": REFERER,
    "Origin": "https://www.lottery.gov.cn",
    "Accept": "application/json, text/plain, */*",
}

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIRNAME = "dlt_raw"
META_NAME = "dlt_meta.json"
PAGE_SIZE = 100


def build_url(page_no: int, page_size: int = PAGE_SIZE, game_no: int = 85) -> str:
    return (f"{BASE_URL}?gameNo={game_no}&provinceId=0"
            f"&pageSize={page_size}&isVerify=1&pageNo={page_no}")


def http_get_json(url: str, retries: int = 5, timeout: int = 30, log=None) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            if not data.get("success"):
                raise RuntimeError(f"接口返回失败：{data.get('errorMessage') or data}")
            return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                RuntimeError) as exc:
            last = exc
            wait = min(2 ** attempt, 20)
            if log:
                log(f"请求失败（{type(exc).__name__}），{wait}s 后重试…")
            time.sleep(wait)
    raise RuntimeError(f"抓取失败：{last}")


def crawl(page_size: int = PAGE_SIZE, delay: float = 0.8, refresh: bool = False,
          data_dir: str | Path | None = None, log=None) -> dict:
    """抓取全部分页并落盘到 ``data/dlt_raw/page_xxx.json``，返回元信息。"""
    root = Path(data_dir or DEFAULT_DATA_DIR)
    raw_dir = root / RAW_DIRNAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    log = log or (lambda _m: None)

    meta_path = raw_dir / META_NAME
    old_total = None
    if meta_path.exists() and not refresh:
        try:
            old_total = json.loads(meta_path.read_text(encoding="utf-8")).get("total")
        except (OSError, json.JSONDecodeError):
            old_total = None

    first = http_get_json(build_url(1, page_size), log=log)
    value = first.get("value", {})
    total = int(value.get("total") or 0)
    pages = int(value.get("pages") or 0)
    if total <= 0 or pages <= 0:
        raise RuntimeError("接口没有返回任何期次，稍后重试")

    reuse = (not refresh and old_total == total
             and all((raw_dir / f"page_{i:03d}.json").exists()
                     for i in range(1, pages + 1)))
    if reuse:
        log(f"数据无变化（{total} 期），复用本地缓存")
    else:
        if old_total is not None and old_total != total:
            log(f"总期数变化（{old_total} → {total}），作废旧页缓存")
        (raw_dir / f"page_{1:03d}.json").write_text(
            json.dumps(first, ensure_ascii=False), encoding="utf-8")
        log(f"共 {total} 期 / {pages} 页，开始抓取…")
        for page in range(2, pages + 1):
            data = http_get_json(build_url(page, page_size), log=log)
            (raw_dir / f"page_{page:03d}.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
            log(f"第 {page}/{pages} 页完成")
            if delay:
                time.sleep(delay)

    meta = {"game": GAME_NAME, "total": total, "pages": pages,
            "page_size": page_size,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (raw_dir / META_NAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    log(f"抓取完成：{total} 期")
    return meta


def peek_total(page_size: int = PAGE_SIZE) -> dict:
    data = http_get_json(build_url(1, page_size))
    value = data.get("value", {})
    return {"total": int(value.get("total") or 0),
            "pages": int(value.get("pages") or 0),
            "latest": (value.get("list") or [{}])[0].get("lotteryDrawNum", "")}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="抓取超级大乐透历史开奖")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--refresh", action="store_true", help="忽略缓存全量重抓")
    args = parser.parse_args(argv)
    meta = crawl(page_size=args.page_size, delay=args.delay,
                 refresh=args.refresh, log=print)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
