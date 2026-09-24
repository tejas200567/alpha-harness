import json, itertools, requests, sqlite3, time, os

SIM_URL = os.environ["BRAIN_SIM_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['BRAIN_TOKEN']}"}

cfg = json.load(open("templates.json"))
regions   = cfg["regions"]
defaults  = cfg["defaults"]
fields    = cfg["fields"]
templates = cfg["templates"]

GROUP_MAP = {"GLB": "subindustry", "USA": "subindustry", "ASI": "country"}

def build_grid():
    grid = []
    for region, rconf in regions.items():
        for tmpl, field in itertools.product(templates, fields[region]):
            expr = tmpl["expr"].format(field=field, group=GROUP_MAP[region])
            settings = {**defaults, **rconf, "region": region}
            grid.append({"name": f"{region}_{tmpl['name']}_{field}",
                         "expression": expr, "settings": settings})
    return grid

conn = sqlite3.connect("alphas.db")
conn.execute("""CREATE TABLE IF NOT EXISTS sims(
    id INTEGER PRIMARY KEY, name TEXT, region TEXT,
    expression TEXT, settings TEXT, status TEXT, sharpe REAL, fitness REAL)""")

grid = build_grid()
print(f"[grid] {len(grid)} simulations queued")

for job in grid:
    r = requests.post(SIM_URL, json={"type": "REGULAR",
                                     "settings": job["settings"],
                                     "regular": job["expression"]},
                      headers=HEADERS)
    if r.status_code == 201:
        sid = r.json().get("id")
        conn.execute("INSERT INTO sims(name,region,expression,settings,status) VALUES(?,?,?,?,?)",
                     (job["name"], job["settings"]["region"], job["expression"],
                      json.dumps(job["settings"]), "queued"))
        conn.commit()
        print(f"[ok] {job['name']} -> {sid}")
    else:
        print(f"[err] {job['name']} -> {r.status_code} {r.text[:120]}")
    time.sleep(0.3)  # throttle to 3 concurrent

print("[done] grid dispatched")
