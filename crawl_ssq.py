#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行入口：抓取双色球开奖数据（等价于 `python -m ssq.core.fetch`）。

用法：
    python crawl_ssq.py                 # 增量抓取（页缓存可复用，总期数变化时自动重抓）
    python crawl_ssq.py --refresh       # 忽略缓存，全量重抓
    python crawl_ssq.py --page-size 100 --delay 1.0
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssq.core.fetch import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
