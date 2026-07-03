import time, httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
S="http://127.0.0.1:8080"
c=httpx.Client(timeout=None, limits=httpx.Limits(max_connections=16))
A='(+ backpack* hiker* trekker*)'
B='(+ bear* "black bear*" "grizzly*")'
C='(+ food* store* "food storage" "food cache*")'
D1='(+ canister* hanging* "campsite selection" "site selection")'
CP='(>> (# 2) (... camp placement))'
D2='(+ canister* hanging* "campsite selection" "site selection" "camp placement")'
cases=[
 ("baseline tier1",              f'(^ {A} {B} {C} {D1})'),
 ("D = phrase ONLY",             f'(^ {A} {B} {C} {CP})'),
 ("D = wildcards + phrase",      f'(^ {A} {B} {C} (+ canister* hanging* {CP}))'),
 ("D2 reordered FIRST",          f'(^ {D2} {A} {B} {C})'),
 ("D2 as-is (culprit)",          f'(^ {A} {B} {C} {D2})'),
]
def run(item):
    label,q=item; t0=time.time()
    try:
        r=c.post(S+"/tools/cover_search",json={"query":q,"top_k":200})
        d=r.json() if r.status_code==200 else {}
        return (label, time.time()-t0, d.get('total_matches'), r.status_code)
    except Exception as e:
        return (label, time.time()-t0, None, type(e).__name__)
print("=== mechanism discrimination (parallel, warm, top_k=200) ===",flush=True)
with ThreadPoolExecutor(max_workers=len(cases)) as ex:
    futs=[ex.submit(run,x) for x in cases]
    for f in as_completed(futs):
        label,dt,m,st=f.result()
        print(f"  DONE {label:26} {dt:9.2f}s  matches={m}  {st if st!=200 else ''}",flush=True)
print("DONE",flush=True)
