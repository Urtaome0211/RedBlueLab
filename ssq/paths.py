# -*- coding: utf-8 -*-
"""路径解析：区分「源码运行」与「PyInstaller 打包后运行」两种形态。

- 源码运行：数据直接读写项目根目录下的 ``data/``，与命令行脚本一致。
- 打包运行：程序目录可能不可写，数据放到 ``%LOCALAPPDATA%\\RedBlueLab\\data``，
  首次启动时把打进包里的一份种子 CSV 复制过去；旧版本（SSQAdvisor）的数据目录
  如果存在，会自动迁移过来。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "RedBlueLab"
LEGACY_APP_NAME = "SSQAdvisor"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """只读资源根目录（打包后是解包临时目录 _MEIPASS）。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", project_root()))
    return project_root()


def _is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def app_root() -> Path:
    """可写的数据根目录：优先 %LOCALAPPDATA%，不可写时退到 exe 旁边、再退到 %TEMP%。"""
    if not is_frozen():
        return project_root()

    candidates: list[Path] = []
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    candidates.append(Path(base) / APP_NAME)
    try:  # 便携模式：放在 exe 同目录（U 盘、绿色版）
        candidates.append(Path(sys.executable).resolve().parent)
    except OSError:
        pass
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        candidates.append(Path(tmp) / APP_NAME)
    candidates.append(Path.home() / APP_NAME)

    for folder in candidates:
        if _is_writable(folder):
            return folder
    return candidates[-1]


ROOT = app_root()
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CONFIG_PATH = ROOT / "config.json"


def ensure_data_dir() -> Path:
    """确保数据目录存在；打包版首次启动时铺一份种子数据。"""
    # 旧版（SSQAdvisor）的数据目录：直接整份搬过来，成绩单和设置都不丢
    legacy = ROOT.parent / LEGACY_APP_NAME
    if legacy.is_dir() and not ROOT.exists():
        try:
            shutil.copytree(legacy, ROOT)
        except OSError:
            pass

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DATA_DIR / "ssq_history.csv"
    if not csv_path.exists():
        seed = resource_root() / "seed" / "ssq_history.csv"
        if seed.exists():
            shutil.copyfile(seed, csv_path)

    # 分页原始数据也铺一份，「重建数据集」才能在离线状态下工作
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not any(RAW_DIR.glob("page_*.json")):
        seed_raw = resource_root() / "seed" / "raw"
        if seed_raw.is_dir():
            for src in seed_raw.glob("page_*.json"):
                shutil.copyfile(src, RAW_DIR / src.name)

    # 大乐透数据（数据集 + 分页缓存）
    dlt_csv = DATA_DIR / "dlt_history.csv"
    if not dlt_csv.exists():
        seed_dlt = resource_root() / "seed" / "dlt_history.csv"
        if seed_dlt.exists():
            shutil.copyfile(seed_dlt, dlt_csv)

    dlt_raw = DATA_DIR / "dlt_raw"
    dlt_raw.mkdir(parents=True, exist_ok=True)
    if not any(dlt_raw.glob("page_*.json")):
        seed_dlt_raw = resource_root() / "seed" / "dlt_raw"
        if seed_dlt_raw.is_dir():
            for src in seed_dlt_raw.glob("page_*.json"):
                shutil.copyfile(src, dlt_raw / src.name)
    return DATA_DIR
