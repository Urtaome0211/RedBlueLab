import pandas as pd, sys
sys.stdout.reconfigure(encoding="utf-8")
df = pd.read_csv("data/ssq_history.csv", encoding="utf-8-sig", dtype={"期号": str})
print("期数", len(df), "|", df["开奖日期"].min(), "->", df["开奖日期"].max())
print("\n最新 7 期：")
print(df.head(7)[["期号", "开奖日期", "红球", "蓝球", "一等奖注数", "一等奖单注奖金(元)", "销售金额(元)", "奖池金额(元)"]].to_string(index=False))

red = pd.concat([df[f"红球{i}"] for i in range(1, 7)]).value_counts()
blue = df["蓝球"].value_counts()
print("\n红球 Top5:", [(f"{k:02d}", int(v)) for k, v in red.head(5).items()])
print("红球 Bottom5:", [(f"{k:02d}", int(v)) for k, v in red.tail(5).items()])
print("蓝球 Top5:", [(f"{k:02d}", int(v)) for k, v in blue.head(5).items()])
print("蓝球 Bottom5:", [(f"{k:02d}", int(v)) for k, v in blue.tail(5).items()])
s = df["红球和值"]
print("和值 80-120 占比: %.1f%%" % (100 * ((s >= 80) & (s <= 120)).mean()))
print("奇偶比 3:3 占比: %.1f%%" % (100 * (df["奇偶比"] == "3:3").mean()))
print("一等奖空开期数:", int((df["一等奖注数"] == 0).sum()),
      "| 单期最多:", int(df["一等奖注数"].max()), df.loc[df["一等奖注数"].idxmax(), "期号"],
      "| 单注最高:", int(df["一等奖单注奖金(元)"].max()), df.loc[df["一等奖单注奖金(元)"].idxmax(), "期号"])
print("近5期蓝球:", df.head(5)["蓝球"].tolist())
print("近5期红球和值:", df.head(5)["红球和值"].tolist())
