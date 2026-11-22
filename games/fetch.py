"""通用抓取：福彩走 cwl.gov.cn，体彩走 webapi.sporttery.cn。

每个彩种独立缓存到 ``data/<key>_raw/page_*.json``，元信息写 ``<key>_meta.json``。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import spec as S

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CWL_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
CWL_REFERER = "https://www.cwl.gov.cn/ygkj/wqkjgg/"
SPORT_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
SPORT_REFERER = "https://www.lottery.gov.cn/"
PAGE_SIZE = 100

ROOT = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    r"""数据目录跟随主程序（打包后是可写的 %LOCALAPPDATA%\RedBlueLab\data）。"""
    try:
        from ssq import paths as app_paths

        return app_paths.ensure_data_dir()
    except Exception:                        # noqa: BLE001 - 单独跑脚本时退回项目目录
        return ROOT / "data"


DATA_DIR = _data_dir()


# ------------------------------------------------------------------ http
def http_get_json(url: str, referer: str, retries: int = 5, timeout: int = 30, log=None):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:                        # noqa: BLE001
            last = exc
            if log:
                log(f"请求失败（第 {attempt + 1} 次）：{exc}")
            time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"抓取失败：{last}")


# ------------------------------------------------------------------ url
def build_url(game: S.GameSpec, page_no: int, page_size: int = PAGE_SIZE) -> str:
    if game.source == "cwl":
        query = {
            "name": game.source_id, "issueCount": "", "issueStart": "", "issueEnd": "",
            "dayStart": "", "dayEnd": "", "pageNo": page_no, "pageSize": page_size,
            "week": "", "systemType": "PC",
        }
        return CWL_URL + "?" + urllib.parse.urlencode(query)
    query = {"gameNo": game.source_id, "provinceId": 0, "pageSize": page_size,
             "isVerify": 1, "pageNo": page_no}
    return SPORT_URL + "?" + urllib.parse.urlencode(query)


def referer_of(game: S.GameSpec) -> str:
    return CWL_REFERER if game.source == "cwl" else SPORT_REFERER


def page_payload(game: S.GameSpec, page_no: int, page_size: int = PAGE_SIZE) -> dict:
    return http_get_json(build_url(game, page_no, page_size), referer_of(game))


def rows_of(game: S.GameSpec, payload: dict) -> list[dict]:
    if game.source == "cwl":
        return payload.get("result") or []
    value = payload.get("value") or {}
    return value.get("list") or []


def total_of(game: S.GameSpec, payload: dict) -> int:
    if game.source == "cwl":
        try:
            return int(payload.get("total") or 0)
        except (TypeError, ValueError):
            return 0
    value = payload.get("value") or {}
    try:
        return int(value.get("total") or 0)
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------ 解析
_MONEY = re.compile(r"(-?[\d,]+(?:\.\d+)?)")


def money(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    text = str(text).strip()
    if not text or text in {"-", "--"}:
        return None
    m = _MONEY.search(text.replace(",", ""))
    return float(m.group(1)) if m else None


def split_money(text) -> tuple[float | None, str]:
    """「5490089（含派奖172413）」这种，拆成金额与备注。"""
    if text is None:
        return None, ""
    text = str(text).strip()
    m = re.match(r"^([\d.]+)\s*(.*)$", text)
    if not m:
        return None, text
    value = float(m.group(1))
    note = m.group(2).strip("（）() ")
    return value, note


def normalize_issue(game: S.GameSpec, raw: str) -> str:
    """统一成 7 位期号：福彩 2026311，体彩 26133 → 2026133。"""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 7:
        return digits
    if len(digits) == 5:
        return "20" + digits
    if len(digits) == 6:
        return "2" + digits
    return digits


def parse_prizes(game: S.GameSpec, row: dict) -> list[dict]:
    """抽出奖级明细：名称、注数、单注奖金。"""
    out: list[dict] = []
    if game.key == "fc3d":
        # 福彩 3D 的 prizegrades 是各玩法的合计派奖，口径与其他彩种不同，按固定奖处理
        return out
    if game.source == "cwl":
        for item in row.get("prizegrades") or []:
            name = str(item.get("type") or "")
            count = money(item.get("typenum"))
            cash = money(item.get("typemoney"))
            if name and (count is not None or cash is not None):
                out.append({"level": name, "count": int(count or 0), "money": cash or 0})
    else:
        for item in row.get("prizeLevelList") or []:
            name = str(item.get("prizeLevel") or "").strip()
            count = money(item.get("stakeCount"))
            cash = money(item.get("stakeAmountFormat") or item.get("stakeAmount"))
            if name:
                out.append({"level": name, "count": int(count or 0), "money": cash or 0})
    return out


def normalize_row(game: S.GameSpec, row: dict) -> dict:
    if game.source == "cwl":
        date_text = str(row.get("date") or "")[:10]
        week = str(row.get("week") or "")
        groups = S.parse_cwl_numbers(game, row.get("red", ""), row.get("blue", ""))
        sales = money(row.get("sales"))
        pool = money(row.get("poolmoney"))
        detail = str(row.get("detailsLink") or "")
        issue = normalize_issue(game, row.get("code"))
    else:
        date_text = str(row.get("lotteryDrawTime") or "")[:10]
        week = ""
        groups = S.parse_sport_numbers(game, row.get("lotteryDrawResult", ""))
        sales = money(row.get("totalSaleAmount"))
        pool = money(row.get("poolBalanceAfterdraw"))
        detail = str(row.get("drawPdfUrl") or "")
        issue = normalize_issue(game, row.get("lotteryDrawNum"))
    return {
        "issue": issue, "date": date_text, "week": week, "groups": groups,
        "sales": sales, "pool": pool, "detail": detail,
        "prizes": parse_prizes(game, row),
    }


# ------------------------------------------------------------------ 缓存
def raw_dir(game: S.GameSpec, base: Path | None = None) -> Path:
    base = Path(base or DATA_DIR)
    return base / f"{game.key}_raw"


def meta_path(game: S.GameSpec, base: Path | None = None) -> Path:
    base = Path(base or DATA_DIR)
    return base / f"{game.key}_meta.json"


def read_meta(game: S.GameSpec, base: Path | None = None) -> dict:
    path = meta_path(game, base)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def read_pages(game: S.GameSpec, base: Path | None = None) -> list[dict]:
    folder = raw_dir(game, base)
    if not folder.exists():
        return []
    rows: list[dict] = []
    for page in sorted(folder.glob("page_*.json")):
        try:
            rows.extend(json.loads(page.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows


def crawl(game: S.GameSpec, page_size: int = PAGE_SIZE, delay: float = 0.8,
          refresh: bool = False, base: Path | None = None, log=None) -> dict:
    base = Path(base or DATA_DIR)
    folder = raw_dir(game, base)
    folder.mkdir(parents=True, exist_ok=True)
    meta = read_meta(game, base)

    # 先问一次总期数：和缓存一致才算「已是最新」，否则继续抓
    first = page_payload(game, 1, page_size)
    total = total_of(game, first)
    pages = max(1, (total + page_size - 1) // page_size)

    if not refresh and meta.get("total") == total and read_pages(game, base):
        if log:
            log(f"{game.name}：已是最新（{total} 期），跳过抓取")
        meta.update({"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        meta_path(game, base).write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return meta

    if log:
        log(f"{game.name}：共 {total} 期 / {pages} 页，开始抓取")

    for page_no in range(1, pages + 1):
        payload = first if page_no == 1 else page_payload(game, page_no, page_size)
        rows = [normalize_row(game, r) for r in rows_of(game, payload)]
        (folder / f"page_{page_no:03d}.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        if log:
            log(f"{game.name}：第 {page_no}/{pages} 页，{len(rows)} 条")
        if page_no < pages:
            time.sleep(delay)

    meta = {"game": game.key, "total": total, "pages": pages, "page_size": page_size,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    meta_path(game, base).write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    return meta


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="抓取指定彩种的历史开奖")
    parser.add_argument("game", nargs="?", default="all", help="彩种 key，或 all")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新抓取")
    parser.add_argument("--delay", type=float, default=0.8)
    args = parser.parse_args(argv)
    games = S.GAMES if args.game == "all" else (S.get(args.game),)
    for game in games:
        meta = crawl(game, delay=args.delay, refresh=args.refresh, log=print)
        print(f"  -> {game.key}: {meta.get('total')} 期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
