import time, httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
S="http://127.0.0.1:8080"
c=httpx.Client(timeout=None, limits=httpx.Limits(max_connections=16))
A='(+ backpack* hiker* trekker*)'
B='(+ bear* "black bear*" "grizzly*")'
C='(+ food* store* "food storage" "food cache*")'
def cover(phrase):  # phrase already includes quotes, or '' for floor
    inner = '(+ canister* hanging*'+((' '+phrase) if phrase else '')+')'
    return f'(^ {A} {B} {C} {inner})'
cases=[
 ("FLOOR (no phrase)",          cover('')),
 ("camp placement  [r=15875]",  cover('"camp placement"')),
 ("site selection  [r=171]",    cover('"site selection"')),
 ("campsite selection [r=99]",  cover('"campsite selection"')),
 ("selection campsite [REV]",   cover('"selection campsite"')),
]
def run(item):
    label,q=item; t0=time.time()
    try:
        r=c.post(S+"/tools/cover_search",json={"query":q,"top_k":200})
        d=r.json() if r.status_code==200 else {}
        return (label, time.time()-t0, d.get('total_matches'), r.status_code)
    except Exception as e:
        return (label, time.time()-t0, None, type(e).__name__)
print("=== TRIGGER TEST: same cover, vary only the phrase (parallel, warm) ===",flush=True)
with ThreadPoolExecutor(max_workers=len(cases)) as ex:
    futs=[ex.submit(run,x) for x in cases]
    for f in as_completed(futs):
        label,dt,m,st=f.result()
        print(f"  DONE {label:28} {dt:9.2f}s  matches={m}  {st if st!=200 else ''}",flush=True)
print("DONE",flush=True)
