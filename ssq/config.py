# -*- coding: utf-8 -*-
"""推荐参数的持久化（JSON）。"""
from __future__ import annotations

import json
from dataclasses import asdict, fields

from . import paths
from .core.recommend import RecParams

DEFAULTS = RecParams()


def load_params() -> RecParams:
    p = DEFAULTS
    try:
        raw = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return p
    valid = {f.name for f in fields(RecParams)}
    kwargs = {k: v for k, v in raw.items() if k in valid and k != "seed"}
    try:
        return RecParams(**{**asdict(p), **kwargs}).validate()
    except (TypeError, ValueError):
        return p


def save_params(params: RecParams) -> None:
    try:
        data = asdict(params)
        data.pop("seed", None)
        paths.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        paths.CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    except OSError:
        pass
