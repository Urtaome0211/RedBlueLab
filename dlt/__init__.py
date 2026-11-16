# -*- coding: utf-8 -*-
"""超级大乐透（体彩）数据与推荐引擎。

玩法：前区 35 选 5 + 后区 12 选 2，单注 2 元；
数据来源：中国体育彩票官网公开接口 ``getHistoryPageListV1.qry``（gameNo=85）。
"""

GAME_NAME = "超级大乐透"
GAME_SHORT = "大乐透"

FRONT_MAX = 35
FRONT_COUNT = 5
BACK_MAX = 12
BACK_COUNT = 2

# 单注组合数：C(35,5) * C(12,2)
TOTAL_COMBOS = 324_632 * 66   # 21,425,712

DLT_VERSION = "1.0.0"
