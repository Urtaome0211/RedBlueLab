# -*- coding: utf-8 -*-
r"""桌面应用入口（`python main.py` 或打包成 exe 后双击）。

窗口模式下没有控制台，异常只会表现为「窗口一闪而过」。这里做了三件事：
1. `--noconsole` 打包后 `sys.stdout/stderr` 是 None，先挂到 os.devnull，
   否则 qfluentwidgets 导入时打印提示会直接抛异常；
2. 启动过程可写日志：设置环境变量 `SSQ_BOOT_LOG=<路径>`；
3. 未捕获异常会写到 `%LOCALAPPDATA%\RedBlueLab\crash.log` 并弹窗提示，
   不会静默退出。
"""
from __future__ import annotations

import os
import sys
import time
import traceback


# PyInstaller --noconsole 打包后 sys.stdout / sys.stderr 是 None，
# qfluentwidgets 导入时会往标准输出打印提示，直接启动会卡死（无控制台可写）。
# 先挂到 os.devnull，后续任何 print 都不会抛异常。
if sys.stdout is None or sys.stderr is None:
    _null = open(os.devnull, "w", encoding="utf-8", errors="replace")  # noqa: SIM115
    sys.stdout = sys.stdout or _null
    sys.stderr = sys.stderr or _null


def _boot(msg: str) -> None:
    path = os.environ.get("SSQ_BOOT_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def _crash_log_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "RedBlueLab")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.environ.get("TEMP") or "."
    return os.path.join(folder, "crash.log")


def _report_crash(text: str) -> None:
    """把崩溃信息写文件并弹窗，避免窗口模式下静默闪退。"""
    path = _crash_log_path()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(f"\n===== {stamp} =====\n{text}\n")
    except OSError:
        path = "(写入失败)"
    tail = "\n".join(text.strip().splitlines()[-12:])
    message = f"程序启动失败，详细信息已写入：\n{path}\n\n{tail}"
    try:  # 不依赖 Qt，Qt 自己都起不来时也能提示
        import ctypes  # noqa: PLC0415

        ctypes.windll.user32.MessageBoxW(None, message[:2000], "RedBlue Lab", 0x10)
    except Exception:  # noqa: BLE001
        pass


def run() -> int:
    _boot(f"start frozen={getattr(sys, 'frozen', False)} argv={sys.argv[1:]}")
    from ssq.ui.main_window import main  # noqa: PLC0415

    _boot("imported ui")
    code = main()
    _boot(f"main returned {code}")
    return code


if __name__ == "__main__":
    _boot("entry")
    try:
        rc = run()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        tb = traceback.format_exc()
        _boot("EXC\n" + tb)
        _report_crash(tb)
        sys.exit(1)
    _boot("exit")
    sys.exit(rc)
