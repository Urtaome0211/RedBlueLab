# -*- coding: utf-8 -*-
"""生成 exe 图标（assets/app.ico / app.png），供 PyInstaller --icon 使用。

用法： .venv\\Scripts\\python.exe tools\\make_icon.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 离屏渲染若找不到字体目录，文字会变成方块
if os.name == "nt" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ssq.ui.main_window import make_icon  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv[:1])
    out = ROOT / "assets"
    out.mkdir(parents=True, exist_ok=True)
    icon = make_icon()
    ok_ico = icon.pixmap(256).save(str(out / "app.ico"))
    ok_png = icon.pixmap(256).save(str(out / "app.png"))
    print(f"ico={ok_ico} png={ok_png} -> {out}")
    del app
    return 0 if (ok_ico and ok_png) else 1


if __name__ == "__main__":
    raise SystemExit(main())
