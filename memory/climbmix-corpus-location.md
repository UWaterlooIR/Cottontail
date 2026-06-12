---
name: climbmix-corpus-location
description: Where the ClimbMix corpus shard files live (outside the repo)
metadata:
  type: reference
---

The ClimbMix corpus (the dataset the climbmix POC indexes) lives **outside the
repo** at `/share/corpora/climbmix-400b-corpus-jsonl/`.

- Files are gzip'd JSONL shards named `shard_NNNNN.jsonl.gz`.
- **20 shards** (`shard_00000.jsonl.gz` … `shard_00019.jsonl.gz`) are present as a
  test subset, confirmed by Mark on 2026-06-12.
- The full corpus is ~6500 such shards (the scaling target for the SimpleWarren
  experiment — see [[project-cottontail-overview]]).

Access note: this path is **outside the repo root**. Mark pointed us here and
authorized using these specific files for the climbmix work; that permission does
**not** generalize to anything else under `/share` (see [[respect-repo-boundary]]).

Ingest: Cottontail's `inhale()` already decompresses `.gz` on the fly via `zcat`,
so `scribe_jsonl` reads these shards directly — no decompression step needed.
