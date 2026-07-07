---
name: climbmix-corpus-location
description: What ClimbMix is (general web corpus — NOT about climbing) and where its shard files live (outside the repo)
metadata:
  type: reference
---

**ClimbMix is a general web/pretraining corpus. It has NOTHING to do with
climbing** — do not craft climbing-themed test queries on that assumption; it
covers broad web/educational text. Provenance: NVIDIA's ClimbMix via
https://huggingface.co/datasets/karpathy/climbmix-400b-shuffle, processed to
JSONL with
https://github.com/TREC-RAG/trec-rag-skills/tree/main/skills/trec-rag-climbmix-corpus-creation.

The corpus (the dataset the climbmix POC indexes) lives **outside the
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
