import time, httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
S="http://127.0.0.1:8080"
c=httpx.Client(timeout=None, limits=httpx.Limits(max_connections=16))
# bare single-word counts (cheap) + standalone phrase timings (the interesting ones)
words=["camp","placement","campsite","site","selection","food","protection","bear","resistant","canister","hanging"]
phrases=[("camp placement",'(>> (# 2) (... camp placement))'),
         ("campsite selection",'(>> (# 2) (... campsite selection))'),
         ("site selection",'(>> (# 2) (... site selection))'),
         ("food protection",'(>> (# 2) (... food protection))'),
         ("bear-resistant",'(>> (# 2) (... bear resistant))')]
def hit(label,q):
    t0=time.time()
    try:
        r=c.post(S+"/tools/cover_search",json={"query":q,"top_k":1})
        d=r.json() if r.status_code==200 else {}
        return (label, time.time()-t0, d.get('total_matches'), r.status_code)
    except Exception as e:
        return (label, time.time()-t0, None, type(e).__name__)
jobs=[("WORD "+w, w) for w in words]+[("PHRASE "+n, q) for n,q in phrases]
print("=== constituent word counts + standalone phrase timings (warm) ===",flush=True)
with ThreadPoolExecutor(max_workers=16) as ex:
    futs=[ex.submit(hit,l,q) for l,q in jobs]
    for f in as_completed(futs):
        label,dt,m,st=f.result()
        print(f"  {label:22} {dt:9.2f}s  count={m}  {st if st!=200 else ''}",flush=True)
print("DONE",flush=True)
