import time, httpx
from concurrent.futures import ThreadPoolExecutor
S="http://127.0.0.1:8080"
c=httpx.Client(timeout=None, limits=httpx.Limits(max_connections=16))
F1='(+ backpack* hiker* trekker*)'
F2='(+ bear* "black bear*" "grizzly*" "bear-resistant")'
F3='(+ food* store* "food storage" "food cache*" "food protection")'
F4='(+ canister* hanging* "campsite selection" "site selection" "camp placement")'
tier1='(^ (+ backpack* hiker* trekker*) (+ bear* "black bear*" "grizzly*") (+ food* store* "food storage" "food cache*") (+ canister* hanging* "campsite selection" "site selection"))'
tier2=f'(^ {F1} {F2} {F3} {F4})'
cases=[("F1 backpack",F1),("F2 bear",F2),("F3 food",F3),("F4 method",F4),("tier1",tier1),("tier2",tier2)]
def run(item):
    label,q=item; t0=time.time()
    try:
        r=c.post(S+"/tools/cover_search",json={"query":q,"top_k":200})
        d=r.json() if r.status_code==200 else {}
        return (label, time.time()-t0, d.get('total_matches'), r.status_code)
    except Exception as e:
        return (label, time.time()-t0, None, type(e).__name__)
for p in (1,2):
    print(f"=== PASS {p} ({'COLD (fresh server)' if p==1 else 'WARM'}) -- all fired in parallel ===",flush=True)
    t0=time.time()
    with ThreadPoolExecutor(max_workers=len(cases)) as ex:
        results=list(ex.map(run,cases))
    wall=time.time()-t0
    for label,dt,m,st in sorted(results,key=lambda x:-x[1]):
        print(f"  {label:12} {dt:9.2f}s  matches={m}  {st if st!=200 else ''}",flush=True)
    print(f"  [pass wall-clock: {wall:.1f}s]",flush=True)
print("DONE",flush=True)
