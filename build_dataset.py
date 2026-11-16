#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行入口：解析原始数据、校验并导出 CSV/JSON/Excel（等价于 `python -m ssq.core.build`）。

用法：
    python build_dataset.py             # 导出三种格式
    python build_dataset.py --no-xlsx   # 跳过 Excel（更快）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssq.core.build import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
