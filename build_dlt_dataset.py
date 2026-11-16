# -*- coding: utf-8 -*-
"""解析大乐透原始数据并导出数据集（命令行入口）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dlt.build import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
