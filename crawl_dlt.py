# -*- coding: utf-8 -*-
"""抓取超级大乐透历史开奖（命令行入口）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dlt.fetch import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
