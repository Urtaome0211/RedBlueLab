import pandas as pd, sys
sys.stdout.reconfigure(encoding="utf-8")
df = pd.read_csv("data/ssq_history.csv", encoding="utf-8-sig", dtype={"期号": str})
picks = [
    ((1, 4, 12, 25, 29, 32), 6),
    ((6, 9, 15, 20, 27, 32), 4),
    ((3, 11, 17, 21, 27, 32), 12),
    ((6, 9, 12, 17, 31, 33), 11),
    ((8, 10, 12, 14, 23, 33), 16),
]
PRIZE = {  # (红球命中, 蓝球命中) -> (奖级, 单注奖金)
    (6, 1): ("一等奖", None), (6, 0): ("二等奖", None), (5, 1): ("三等奖", 3000),
    (5, 0): ("四等奖", 200), (4, 1): ("四等奖", 200), (4, 0): ("五等奖", 10),
    (3, 1): ("五等奖", 10), (2, 1): ("六等奖", 5), (1, 1): ("六等奖", 5), (0, 1): ("六等奖", 5),
}
rows = df[df["期号"] >= "2026123"]
total = 0
for _, r in rows.iterrows():
    reds = {int(x) for x in r["红球"].split(",")}
    for i, (pr, pb) in enumerate(picks, 1):
        hit_r, hit_b = len(reds & set(pr)), int(r["蓝球"]) == pb
        if (hit_r, hit_b) in PRIZE:
            lvl, money = PRIZE[(hit_r, hit_b)]
            money = money if money is not None else int(r["一等奖单注奖金(元)"])
            total += money
            print(f"{r['期号']} 第{i}注 中 {hit_r} 红 + 蓝{'√' if hit_b else '×'} -> {lvl} {money} 元")
print(f"\n5 注 × 5 期 = 25 注，共投入 50 元，中奖 {total} 元")
