---
id: TASK-13
title: >-
  GCL: single-operand (+ word) and (^ word) should be valid (identity), not an
  error
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 17:52'
updated_date: '2026-06-26 18:08'
labels:
  - gcl
  - core
dependencies: []
priority: high
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In GCL, ONE_OF (+) and ALL_OF (^) with a SINGLE operand are currently unconstructible: SExpression::to_hopper (src/parse.cc) returns nullptr whenever subx_.size() < 2, so (+ word) and (^ word) fail to build with "Could not construct hopper from valid gcl". Note the grammar already accepts them -- the min_operands table allows 1 operand for + and ^ -- so they PARSE as valid; only to_hopper rejects them. That is an inconsistency written by a human who would simply type the bare word: (+ word), (^ word), and word are all the same thing. A 1-ary Or/And is identity = its single element.

WHY IT MATTERS: the LLM Searcher naturally writes a one-term facet as (+ hiker*) or (+ "first aid"). Today each such group fails, AND it poisons any enclosing expression -- a single (+ X) makes the whole cover query fail (since TASK-7 this is a clean 400; before TASK-7 it segfaulted). In one TASK-11 E2E run this caused 7 engine_error bounces -- 7 wasted Searcher turns, each re-sending the ~80K-token context. Fixing it removes a whole class of agent failures.

DESIRED: (+ word) reduces to word and (^ word) reduces to word -- a single-operand ONE_OF/ALL_OF constructs as its child hopper (identity). The variadic binary operators (>> << !> !< followed_by ...) still correctly require 2 operands; an empty group (0 operands) stays invalid.

EVIDENCE (current, against the 1M porter burrow): "(+ hiker*)" -> error; "(^ bear* (+ hiker*))" -> error; "(^ bear* hiker*)" -> OK (168 matches); "(^ bear* (+ hiker* trekker*))" -> OK. After the fix the first two must succeed and match their bare-word equivalents.

Same code site as the TASK-7 segfault fix.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A single-operand ONE_OF/ALL_OF constructs successfully and is SEMANTICALLY IDENTICAL to the bare element: hopper_from_gcl("(+ word)") and hopper_from_gcl("(^ word)") return a non-null hopper that behaves exactly like hopper_from_gcl("word") (same tau/rho/uat/ohr and same ranking). Fix in SExpression::to_hopper (src/parse.cc): for subx_.size()==1 with kind ONE_OF or ALL_OF, return the single child to_hopper(...) instead of nullptr.
- [x] #2 A single-operand group nested in a larger expression no longer poisons it: "(^ bear* (+ hiker*))" constructs and returns the same results as "(^ bear* hiker*)".
- [x] #3 Other operators are unaffected: the variadic BINARY operators (>> << !> !< followed_by contained_in ...) still return nullptr for fewer than 2 operands; an EMPTY group "(+ )" / "(^ )" (0 operands) stays invalid; TERM / FIXED / LINK are unchanged.
- [x] #4 Regression test in test/gcl.cc: assert "(+ w)" and "(^ w)" build and produce the SAME postings as "w"; assert the nested "(^ a (+ b))" equals "(^ a b)"; assert a binary op with one operand (e.g. "(>> a)") still returns null. bazel test //test:tests //test:jsonl_test //test:jsonl_server_test stays green.
- [x] #5 End-to-end check: a cover_search whose facets include single-term (+ ...) groups (e.g. the black-bear query that bounced 7x in the TASK-11 E2E) now CONSTRUCTS instead of returning 400.
- [x] #6 The reduction is noted where GCL / cover-query syntax is documented (so the contract is not stale): (+ X) and (^ X) reduce to X.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DECISION (user): also update the agent describe_json cover_search hint (single words read nicer than (+ word)/(^ word)).

1. src/parse.cc, SExpression::to_hopper: just before "if (subx_.size() < 2) return nullptr;", add:
   if (subx_.size() == 1 && (kind_ == ONE_OF || kind_ == ALL_OF)) return subx_[0]->to_hopper(featurizer, idx);
   A 1-ary Or/And is identity. Composes with existing logic: nested (+ (+ X)) recurses to X; invalid child still propagates null (TASK-7 intact); empty (+ )/(^ ) (0 operands) stays invalid via the < 2 path; binary ops (>> << !> !< followed_by) with 1 operand still nullptr; > 2 already handled by to_binary. No parser change (min_operands already allows 1 for +/^).

2. test/gcl.cc, new TEST(GCLTest, SingleOperandIsIdentity): small in-memory warren ("alpha beta gamma delta"); a walk(gcl) helper that asserts non-null and returns the tau-walk of (p,q). Assert walk("(+ alpha)")==walk("alpha"); walk("(^ alpha)")==walk("alpha"); walk("(^ alpha (+ beta))")==walk("(^ alpha beta)"); hopper_from_gcl("(>> alpha)")==nullptr (binary still needs 2). Existing NullSubexpressionDoesNotCrash stays green.

3. Docs: a one-line note that (+ X) and (^ X) reduce to X in docs/cottontail-jsonl-cli-spec.md (cover query syntax, sec 4.2) and docs/cottontail-search-server-spec.md.

4. Agent prompt: apps/jsonl_json.cc describe_json cover_search hint -- note that a single term needs no (+ )/(^ ) wrapper (write the bare word).

VERIFY: bazel build //apps:cottontail-jsonl-query; standalone re-run the four evidence cases ((+ hiker*) and (^ bear* (+ hiker*)) now construct, the latter matches (^ bear* hiker*); controls still OK). GATE: bazel test //test:tests //test:jsonl_test //test:jsonl_server_test green. Same code site as the TASK-7 fix.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Fix site: SExpression::to_hopper in src/parse.cc (just before the existing "if (subx_.size() < 2) return nullptr;"). Restrict the identity case to ONE_OF and ALL_OF (the variadic And/Or); leave the binary relations requiring 2. The grammar already permits 1 operand (gcl_operator_min_operands has ONE_OF=1, ALL_OF=1), so no parser change is needed -- only to_hopper. Discovered via the TASK-11 E2E (7 engine_error bounces on single-term (+ ) / (^ ) facets). Same area as the TASK-7 null-child segfault fix.

IMPLEMENTED. src/parse.cc SExpression::to_hopper: before the "subx_.size() < 2 -> nullptr", added "if (subx_.size()==1 && (kind_==ONE_OF||kind_==ALL_OF)) return subx_[0]->to_hopper(featurizer, idx);" -- a 1-ary Or/And returns its child (identity). Nested (+ (+ X)) recurses; an invalid child still propagates null (TASK-7 intact); binary ops with 1 operand and empty groups stay null. No parser change (min_operands already allows 1 for +/^).

test/gcl.cc: new TEST(GCLTest, SingleOperandIsIdentity) -- walk("(+ alpha)")==walk("alpha"), walk("(^ alpha)")==walk("alpha"), walk("(+ (+ alpha))")==walk("alpha"), walk("(^ alpha (+ beta))")==walk("(^ alpha beta)"), and hopper_from_gcl("(>> alpha)")==nullptr (binary still needs 2). Also UPDATED the TASK-7 test NullSubexpressionDoesNotCrash: its poison was "(^ x)" which TASK-13 now makes valid, so it was failing; swapped to a NESTED binary-with-one-operand "(>> x)" (parses since sub-expression arity is not enforced at parse, but to_hopper builds null) -- so it still exercises the TASK-7 null-propagation guard. Both green.

apps/jsonl_json.cc: cover_search describe hint now says (+ a b) is for TWO OR MORE alternatives; a single term needs no wrapper (write the bare word, e.g. bear* not (+ bear*)). docs/cottontail-jsonl-cli-spec.md + docs/cottontail-search-server-spec.md note that (+ X) and (^ X) reduce to X.

GATE: bazel test //test:tests //test:jsonl_test //test:jsonl_server_test all green. LIVE (1M porter burrow): "(+ hiker*)" -> OK 1212; "(^ bear* (+ hiker*))" -> OK 168, IDENTICAL cp list to "(^ bear* hiker*)"; the black-bear single-term-facet query "(^ black bear* (+ attack* maul*) (+ hiker*) (+ \"first aid\"))" now constructs (2 matches) instead of 400.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
GCL now treats a single-operand Or/And as identity: (+ X) and (^ X) reduce to X. A one-line change in SExpression::to_hopper (src/parse.cc) returns the single child for a 1-operand ONE_OF/ALL_OF instead of nullptr; binary relations still require 2 operands and empty groups stay invalid. This removes a whole class of Searcher failures -- the LLM naturally writes one-term facets like (+ hiker*) / (+ "first aid"), which used to fail and poison the entire cover query (7 engine_error bounces in one E2E; a 400 since TASK-7, a segfault before it). Verified: (+ hiker*) and (^ bear* (+ hiker*)) now construct and return results identical to their bare-word forms; the E2E culprit query now constructs. Updated the TASK-7 regression test (its old (^ x) poison is now valid) to use a nested binary-with-one-operand, the new SingleOperandIsIdentity test, the agent cover_search prompt (write the bare word, no single-term wrapper), and the CLI/server docs. Full C++ test gate green.
<!-- SECTION:FINAL_SUMMARY:END -->
