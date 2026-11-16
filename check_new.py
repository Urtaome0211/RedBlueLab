import json, urllib.request, sys, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
BASE = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
       "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/", "X-Requested-With": "XMLHttpRequest"}
q = "name=ssq&issueCount=&issueStart=&issueEnd=&dayStart=&dayEnd=&pageNo=1&pageSize=100&week=&systemType=PC"
d = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "?" + q, headers=HDR), timeout=30).read().decode("utf-8"))
df = pd.read_csv("data/ssq_history.csv", encoding="utf-8-sig", dtype={"期号": str})
old_max = df["期号"].max()
print(f"本地最新: {old_max} | 接口 total={d['total']} pageNum={d['pageNum']} | 本地 {len(df)} 期")
new = [x for x in d["result"] if x["code"] > old_max]
print(f"新增 {len(new)} 期:")
for x in sorted(new, key=lambda y: y["code"]):
    g = x["prizegrades"][0]
    print(f"  {x['code']} {x['date']}  红 {x['red']}  蓝 {x['blue']}  一等奖 {g['typenum']} 注/{g['typemoney']} 元  奖池 {int(x['poolmoney'])/1e8:.2f} 亿  销量 {int(x['sales'])/1e8:.2f} 亿")
