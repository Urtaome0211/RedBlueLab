# -*- coding: utf-8 -*-
"""重建快乐8 / 福彩3D / 七乐彩 / 7星彩 / 排列3 / 排列5 的数据集。

用法：
    python build_games_dataset.py kl8
    python build_games_dataset.py all
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from games import spec as S  # noqa: E402
from games.build import main as build_main  # noqa: E402

ALL = ("kl8", "fc3d", "qlc", "qxc", "pl3", "pl5")


def cli(argv: list[str]) -> int:
    keys = [a for a in argv[1:] if not a.startswith("-")]
    flags = [a for a in argv[1:] if a.startswith("-")]
    if not keys or "all" in keys:
        keys = list(ALL)
    bad = [k for k in keys if k not in S.GAME_MAP]
    if bad:
        print(f"未知彩种：{', '.join(bad)}")
        return 2
    for key in keys:
        code = build_main([key, *flags])
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(cli(sys.argv))
