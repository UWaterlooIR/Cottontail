import time, httpx
c=httpx.Client(timeout=None)
S="http://127.0.0.1:8080"
for label,q in [("camp placement (full enum)", '(>> (# 2) (... camp placement))'),
                ("selection campsite (full enum)", '(>> (# 2) (... selection campsite))')]:
    t0=time.time()
    r=c.post(S+"/tools/cover_search",json={"query":q,"top_k":200})
    d=r.json()
    print(f"{label:32} {time.time()-t0:8.2f}s  matches={d.get('total_matches')}",flush=True)
