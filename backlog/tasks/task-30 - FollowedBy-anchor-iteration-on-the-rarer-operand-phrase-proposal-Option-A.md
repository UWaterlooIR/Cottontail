---
id: TASK-30
title: 'FollowedBy: anchor iteration on the rarer operand (phrase proposal Option A)'
status: To Do
assignee: []
created_date: '2026-07-03 14:52'
labels: []
dependencies: []
priority: high
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Option A of docs/design/phrase-search-performance-and-proposal.md (incl. Addendum 2). FollowedBy(A,B) currently always drives from A — one candidate interval per occurrence of the FIRST word (gcl/gcl.cc, FollowedBy::L_/R_) — so a phrase's cost is O(freq(first word)) and reversing two words swings cost 53x ("campsite selection" 15s vs "selection campsite" 806s on the 100M burrow, identical vocabulary and results).

Change: at hopper-construction time (gcl/parse.cc to_hopper has featurizer+idx in hand; idx->count() is cheap — it reads only the posting header), build FollowedBy so iteration is DRIVEN by whichever operand is rarer, verifying the other at the required offset/direction. Cost becomes O(freq(rarer)) and word order stops mattering. v1 scope: decide drive direction only when both operands' costs are estimable (TERM/FIXED leaves — which covers all parser-generated phrases, where operands are terms or nested FollowedBy chains built from terms; for a compound operand, estimate by its rarest term or keep today's left drive).

SEMANTICS GATE (the proposal's Open Question 3): FollowedBy's emitted CANDIDATE intervals are [A, next-B-after-A], one per A; driving from B enumerates candidates per-B, so the intermediate interval STREAM can differ even though the enclosing (# N) containment yields the same phrase matches. Must verify no caller depends on candidate-interval identity: audit uses of FollowedBy ('...' queries OUTSIDE the (>> (# N) ...) phrase form — bare (... a b) is user-writable GCL and the MultiText <> operator emits it). If bare-FollowedBy identity matters, preserve today's stream for the bare case and swap drive only under the phrase compile — decide during implementation and DOCUMENT the choice.

FORK DIVERGENCE NOTE: first intentional change inside gcl/ (upstream-owned code). Keep the diff minimal, self-contained, and upstreamable; the proposal doc is the accompanying rationale for Charlie. Mark decides when/how to share.

Validation (proposal Part IV): identical total_matches and top-k on ALL Part I/III queries (5,765 for the tiers — non-negotiable); "selection campsite" skeleton falls from ~806s to ~"campsite selection" level (~15s); "camp placement" is EXPECTED UNCHANGED (its rare word already leads — that is TASK-31's case); fast dense phrases stay fast; bazel //test:all green (gcl tests esp.).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 FollowedBy drive direction is chosen by idx counts at construction; phrase cost is O(freq(rarer word)) — the reversed-phrase skeleton query drops from ~806s to roughly the forward-order cost on the 100M burrow
- [ ] #2 Semantics gate passed: all Part I/III validation queries return identical total_matches and top-k; the bare-FollowedBy identity question (Open Question 3) is resolved and documented in the code and task notes
- [ ] #3 The diff is confined to gcl/ (construction/drive logic), minimal and upstreamable; bazel //test:all and the isj suite stay green
<!-- AC:END -->
