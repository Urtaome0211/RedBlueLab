"""各个彩种的元数据与号码结构定义。

每个彩种用 Zone 描述「一组号码」：快乐8 是一组 20 个号，福彩3D 是三个有序位，
七乐彩是 7 个基本号 + 1 个特别号，7 星彩是 6 位 0-9 + 1 位 0-14。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Zone:
    """一组号码。ordered=True 表示位置有意义（3D 的百位/个位）。"""

    label: str
    count: int
    lo: int
    hi: int
    ordered: bool = False

    @property
    def size(self) -> int:
        return self.hi - self.lo + 1

    @property
    def width(self) -> int:
        """显示宽度：两位数号段补零。"""
        return 2 if self.hi >= 10 else 1


@dataclass(frozen=True)
class GameSpec:
    key: str
    name: str
    short: str
    category: str            # "福彩" / "体彩"
    source: str              # "cwl" / "sport"
    source_id: str           # cwl: name=kl8；sport: gameNo=04
    zones: tuple[Zone, ...]
    ticket: tuple[int, ...]  # 一注在各 zone 各选几个号
    play: str                # 玩法说明，例如「选十」「直选」
    summary: str             # 一句话说明
    prize_note: str = ""
    stats_keys: tuple[str, ...] = ("sum", "span", "odd", "big")

    # ---------------------------------------------------------------- 号码
    def ticket_count(self) -> int:
        """一注包含的号码总数。"""
        return sum(self.ticket)

    def zone_of(self, index: int) -> Zone:
        return self.zones[index]


def _digits(n: int, hi: int = 9, label: str = "位") -> tuple[Zone, ...]:
    return tuple(Zone(f"第{i + 1}位", 1, 0, hi if i == n - 1 and hi != 9 else 9, True)
                 for i in range(n))


QLC = GameSpec(
    key="qlc", name="七乐彩", short="七乐彩", category="福彩", source="cwl", source_id="qlc",
    zones=(Zone("基本号", 7, 1, 30), Zone("特别号", 1, 1, 30)),
    ticket=(7, 0), play="基本号选 7 个",
    summary="从 1-30 中选 7 个基本号，再开 1 个特别号",
    prize_note="一、二等奖浮动，三至七等奖固定",
)

KL8 = GameSpec(
    key="kl8", name="快乐8", short="快乐8", category="福彩", source="cwl", source_id="kl8",
    zones=(Zone("号码", 20, 1, 80),),
    ticket=(10,), play="选十",
    summary="每期开 20 个号，这里按「选十」玩法推荐 10 个号",
    prize_note="选十玩法：中 10 个 500 万，中 0 个也有 2 元",
)

FC3D = GameSpec(
    key="fc3d", name="福彩3D", short="3D", category="福彩", source="cwl", source_id="3d",
    zones=(Zone("百位", 1, 0, 9, True), Zone("十位", 1, 0, 9, True), Zone("个位", 1, 0, 9, True)),
    ticket=(1, 1, 1), play="直选",
    summary="三位数字，按位对奖（直选）",
    prize_note="直选 1040 元，组选三 346 元，组选六 173 元",
)

QXC = GameSpec(
    key="qxc", name="7星彩", short="7星彩", category="体彩", source="sport", source_id="04",
    zones=(Zone("前六位", 6, 0, 9, True), Zone("第七位", 1, 0, 14, True)),
    ticket=(6, 1), play="单式",
    summary="前 6 位各 0-9，第 7 位 0-14",
    prize_note="一等奖浮动",
)

PL3 = GameSpec(
    key="pl3", name="排列3", short="排列3", category="体彩", source="sport", source_id="35",
    zones=(Zone("百位", 1, 0, 9, True), Zone("十位", 1, 0, 9, True), Zone("个位", 1, 0, 9, True)),
    ticket=(1, 1, 1), play="直选",
    summary="三位数字，按位对奖（直选）",
    prize_note="直选 1040 元，组选三 346 元，组选六 173 元",
)

PL5 = GameSpec(
    key="pl5", name="排列5", short="排列5", category="体彩", source="sport", source_id="350133",
    zones=(Zone("第1位", 1, 0, 9, True), Zone("第2位", 1, 0, 9, True), Zone("第3位", 1, 0, 9, True),
           Zone("第4位", 1, 0, 9, True), Zone("第5位", 1, 0, 9, True)),
    ticket=(1, 1, 1, 1, 1), play="直选",
    summary="五位数字，全部按位对中即中 10 万元",
    prize_note="固定奖 10 万元",
)

GAMES: tuple[GameSpec, ...] = (QLC, KL8, FC3D, QXC, PL3, PL5)
GAME_MAP = {g.key: g for g in GAMES}


def get(key: str) -> GameSpec:
    return GAME_MAP[key]


# ------------------------------------------------------------------ 解析
def parse_cwl_numbers(spec: GameSpec, red: str, blue: str) -> list[list[int]]:
    """把福彩接口的 red/blue 字符串拆成按 zone 分组的号码。"""
    reds = [int(x) for x in re.split(r"[,\s]+", (red or "").strip()) if x.strip().isdigit()]
    blues = [int(x) for x in re.split(r"[,\s]+", (blue or "").strip()) if x.strip().isdigit()]
    out: list[list[int]] = []
    pos = 0
    for i, zone in enumerate(spec.zones):
        if i > 0 and i == len(spec.zones) - 1 and zone.label == "特别号" and blues:
            out.append(blues[:zone.count])
            continue
        if i > 0 and not reds[pos:]:
            out.append(blues[:zone.count] if blues else [])
            continue
        out.append(reds[pos:pos + zone.count])
        pos += zone.count
    return out


def parse_sport_numbers(spec: GameSpec, result: str) -> list[list[int]]:
    """把体彩接口的 '6 2 1 8 9 2 5' 拆成按 zone 分组。"""
    nums = [int(x) for x in re.split(r"[,\s]+", (result or "").strip()) if x.strip().isdigit()]
    out: list[list[int]] = []
    pos = 0
    for zone in spec.zones:
        out.append(nums[pos:pos + zone.count])
        pos += zone.count
    return out


def format_zone(zone: Zone, nums: list[int]) -> str:
    if zone.ordered:
        return " ".join(str(n) for n in nums)
    return ",".join(f"{n:0{zone.width}d}" for n in nums)


def ticket_text(spec: GameSpec, groups: list[list[int]]) -> str:
    """号码的可读形式，例如 3D 的 '8 1 5' 或七乐彩的 '02,05,...  + 08'。"""
    parts = []
    for zone, nums in zip(spec.zones, groups):
        if not nums:
            continue
        text = format_zone(zone, nums)
        parts.append(text if len(spec.zones) == 1 or zone.ordered else text)
    if len(parts) > 1 and spec.zones[1].label == "特别号":
        return f"{parts[0]} + {parts[1]}"
    return " ".join(parts)
