# -*- coding: utf-8 -*-
"""数据抓取：官方前端接口分页拉取 + 页级缓存 + 总期数变化自动失效。"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .. import paths

BASE_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
REFERER = "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Referer": REFERER,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}

Log = Callable[[str], None]


def build_url(page_no: int, page_size: int) -> str:
    params = [
        ("name", "ssq"), ("issueCount", ""), ("issueStart", ""), ("issueEnd", ""),
        ("dayStart", ""), ("dayEnd", ""), ("pageNo", str(page_no)),
        ("pageSize", str(page_size)), ("week", ""), ("systemType", "PC"),
    ]
    return BASE_URL + "?" + "&".join(f"{k}={v}" for k, v in params)


def http_get_json(url: str, retries: int = 5, timeout: int = 30,
                  log: Log | None = None) -> dict:
    """带指数退避重试的 GET。"""
    ctx = ssl.create_default_context()
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read()
            return json.loads(body.decode("utf-8", "replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError, OSError) as exc:
            last_err = exc
            wait = min(2 ** attempt, 20)
            if log:
                log(f"第 {attempt}/{retries} 次请求失败：{type(exc).__name__}: {exc}；{wait}s 后重试")
            time.sleep(wait)
    raise RuntimeError(f"请求失败（已重试 {retries} 次）：{url}") from last_err


def crawl(page_size: int = 100, delay: float = 1.0, refresh: bool = False,
          data_dir: Path | str | None = None, log: Log | None = None) -> dict:
    """抓取全部分页并落盘，返回 meta（含 total / page_num / fetched_at）。"""
    log = log or (lambda msg: None)
    raw_dir = Path(data_dir or paths.DATA_DIR) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta_path = raw_dir / "meta.json"

    if refresh:
        for old in raw_dir.glob("page_*.json"):
            old.unlink()

    # 缓存按「页号」存，但新期开奖会让所有记录整体后移、旧页内容随之错位，
    # 因此只要服务端总期数变了，就必须作废全部页缓存重抓。
    old_meta: dict = {}
    if meta_path.exists():
        try:
            old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old_meta = {}

    log("抓取第 1 页…")
    first = http_get_json(build_url(1, page_size), log=log)
    (raw_dir / "page_001.json").write_text(json.dumps(first, ensure_ascii=False),
                                           encoding="utf-8")

    total = int(first.get("total") or 0)
    page_num = int(first.get("pageNum") or 0)
    log(f"服务端：共 {total} 期 / {page_num} 页")

    stale = bool(old_meta) and old_meta.get("total") != total and not refresh
    if stale:
        log(f"总期数变化（{old_meta.get('total')} → {total}），作废旧页缓存并全量重抓")
        for old in raw_dir.glob("page_*.json"):
            if old.name != "page_001.json":
                old.unlink()
        # 首页也要用最新内容：page_001.json 已覆盖写入

    meta = {"source": BASE_URL, "referer": REFERER, "page_size": page_size,
            "total": total, "page_num": page_num,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    for page_no in range(2, page_num + 1):
        path = raw_dir / f"page_{page_no:03d}.json"
        if path.exists() and not refresh:
            log(f"第 {page_no}/{page_num} 页已缓存，跳过")
            continue
        log(f"抓取第 {page_no}/{page_num} 页…")
        data = http_get_json(build_url(page_no, page_size), log=log)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        log(f"第 {page_no}/{page_num} 页：{len(data.get('result') or [])} 条")
        time.sleep(delay)

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def peek_total(retries: int = 2, log: Log | None = None) -> int:
    """只请求首页，拿服务端当前总期数（用于「检查是否有新开奖」）。"""
    data = http_get_json(build_url(1, 5), retries=retries, log=log)
    return int(data.get("total") or 0)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="爬取双色球往期开奖记录")
    ap.add_argument("--page-size", type=int, default=100, help="每页条数（默认 100）")
    ap.add_argument("--delay", type=float, default=1.0, help="请求间隔秒数（默认 1.0）")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新抓取")
    args = ap.parse_args(argv)

    def log(msg: str) -> None:
        print("   " + msg)

    t0 = time.time()
    meta = crawl(args.page_size, args.delay, args.refresh, log=log)
    print(f"完成：{meta['total']} 期，用时 {time.time() - t0:.1f}s → {paths.RAW_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
