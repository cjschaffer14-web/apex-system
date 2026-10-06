import sys, json, glob, time
sys.path.insert(0, '/home/claude/build/APEX_v0_4')
from apex.ext import research_v05 as rv
data = {}
for f in glob.glob("*_86400.json"):
    prod = f.split("_")[0]
    if prod == "MATIC-USD":
        continue
    data[prod] = {ts // 86400: (c, v) for ts, o, h, l, c, v in json.load(open(f))}
panel = rv.Panel.from_dict(data)
t = time.time()
res = rv.run_research(panel)
print("seconds", round(time.time() - t, 1), "products", res["products"], res["first_day"], res["last_day"], "rebalances", res["rebalances"])
print("IC", json.dumps(res["ic"]))
print("books", json.dumps(res["books"]))
print("benchmarks", json.dumps(res["benchmarks"]))
print("PBO", res["evidence"]["pbo_family"], "trials", res["evidence"]["trials_counted"])
for k, v in sorted(res["evidence"]["rows"].items(), key=lambda kv: -kv[1]["evidence"]):
    print(f"{k:34s} {json.dumps(v)}")
print("beta", json.dumps(res["last_beta"]))
