---
name: dev-burrow-climbmix-100k
description: new-style porter dev index at Scrapheap/climbmix-100k-porter.burrow for Searcher cp/sidecar work
metadata:
  type: project
---

The dev/test target for resuming the Searcher (TASK-5) work is
`Scrapheap/climbmix-100k-porter.burrow` (in-repo, gitignored): a **new-style**
index (contents + `:item` + `cp↔docno` sidecar, **no `:docno`**) built by the
TASK-6.2 `cottontail-jsonl-index`, porter-stemmed (`--stem porter`), ~100k docs
from ClimbMix (see [[climbmix-corpus-location]]).

Use this for developing/testing the retrieval-side cutover and the B2/C3 live
gates. The older `Scrapheap/climbmix-1000-*porter.burrow` is **old-style**
(`:docno`) and incompatible with the new query path. See [[climbmix-poc-plan]].
