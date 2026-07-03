import time, httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
S="http://127.0.0.1:8080"
c=httpx.Client(timeout=None, limits=httpx.Limits(max_connections=16))
A='(+ backpack* hiker* trekker*)'
B1='(+ bear* "black bear*" "grizzly*")'
C1='(+ food* store* "food storage" "food cache*")'
D1='(+ canister* hanging* "campsite selection" "site selection")'
B2='(+ bear* "black bear*" "grizzly*" "bear-resistant")'
C2='(+ food* store* "food storage" "food cache*" "food protection")'
D2='(+ canister* hanging* "campsite selection" "site selection" "camp placement")'
def AND(*f): return '(^ '+' '.join(f)+')'
cases=[
 ("tier1 (baseline)",       AND(A,B1,C1,D1)),
 ("+bear-resistant (B)",    AND(A,B2,C1,D1)),
 ("+food protection (C)",   AND(A,B1,C2,D1)),
 ("+camp placement (D)",    AND(A,B1,C1,D2)),
 ("tier2 (all three)",      AND(A,B2,C2,D2)),
]
def run(item):
    label,q=item; t0=time.time()
    try:
        r=c.post(S+"/tools/cover_search",json={"query":q,"top_k":200})
        d=r.json() if r.status_code==200 else {}
        return (label, time.time()-t0, d.get('total_matches'), r.status_code)
    except Exception as e:
        return (label, time.time()-t0, None, type(e).__name__)
print("=== tier1 -> tier2 decomposition (parallel, warm cache, top_k=200) ===",flush=True)
t0=time.time()
with ThreadPoolExecutor(max_workers=len(cases)) as ex:
    futs={ex.submit(run,c):c for c in cases}
    for f in as_completed(futs):
        label,dt,m,st=f.result()
        print(f"  DONE {label:22} {dt:9.2f}s  matches={m}  {st if st!=200 else ''}",flush=True)
print(f"[wall-clock: {time.time()-t0:.1f}s]",flush=True)
