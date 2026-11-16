import random, pandas as pd, sys
sys.stdout.reconfigure(encoding="utf-8")
df = pd.read_csv("data/ssq_history.csv", encoding="utf-8-sig", dtype={"期号": str})

TOTAL = 17721088
avg1, avg2 = df["一等奖单注奖金(元)"].mean(), df["二等奖单注奖金(元)"].mean()
fixed = 162*3000 + 7695*200 + 137475*10 + 1043640*5
ev = (1*avg1 + 15*avg2 + fixed) / TOTAL
print(f"每注 2 元期望回报 ≈ {ev:.3f} 元（返还率 {ev/2:.1%}），头奖概率 1/{TOTAL:,}")

# 卡方检验：历史冷热号差异是否超出随机波动
red = pd.concat([df[f"红球{i}"] for i in range(1, 7)])
obs_r = red.value_counts().reindex(range(1, 34), fill_value=0)
exp_r = len(red) / 33
chi_r = ((obs_r - exp_r) ** 2 / exp_r).sum()
obs_b = df["蓝球"].value_counts().reindex(range(1, 17), fill_value=0)
exp_b = len(df) / 16
chi_b = ((obs_b - exp_b) ** 2 / exp_b).sum()
print(f"红球卡方 χ²={chi_r:.1f} (df=32, 5% 临界值 46.19) -> {'不显著，与均匀随机一致' if chi_r < 46.19 else '显著'}")
print(f"蓝球卡方 χ²={chi_b:.1f} (df=15, 5% 临界值 25.00) -> {'不显著，与均匀随机一致' if chi_b < 24.996 else '显著'}")

rng = random.Random(20261026)
pool = []
for _ in range(200000):
    reds = tuple(sorted(rng.sample(range(1, 34), 6)))
    blue = rng.randint(1, 16)
    z = (sum(1 for x in reds if x <= 11), sum(1 for x in reds if 12 <= x <= 22),
         sum(1 for x in reds if x >= 23))
    if not all(v >= 1 for v in z):                 # 三区都有号，形态自然
        continue
    if not (90 <= sum(reds) <= 120):               # 和值落在最高概率区间
        continue
    if sum(1 for x in reds if x >= 32) == 0:       # 至少含一个 32/33（人类偏好低估大号）
        continue
    if any(reds[i+1] - reds[i] == 1 for i in range(5)):  # 不要连号
        continue
    pool.append((reds, blue))

picks, used_blue = [], set()
for reds, blue in pool:
    if blue in used_blue:                          # 蓝球分散，覆盖更多开奖情形
        continue
    if any(len(set(reds) & set(p[0])) > 2 for p in picks):  # 注间重合 ≤2，避免全盘同生共死
        continue
    picks.append((reds, blue)); used_blue.add(blue)
    if len(picks) == 5:
        break

print("\n5 注：")
for i, (r, b) in enumerate(picks, 1):
    odd = sum(1 for x in r if x % 2)
    z = (sum(1 for x in r if x <= 11), sum(1 for x in r if 12 <= x <= 22), sum(1 for x in r if x >= 23))
    print(f"  {i}. 红 {' '.join(f'{x:02d}' for x in r)} + 蓝 {b:02d}"
          f" | 和值 {sum(r):3d} 跨度 {max(r)-min(r):2d} 奇偶 {odd}:{6-odd} 三区 {z[0]}:{z[1]}:{z[2]}")
print(f"\n10 元投入，期望回报 ≈ {ev*5:.2f} 元；中头奖概率 5/{TOTAL:,}")
