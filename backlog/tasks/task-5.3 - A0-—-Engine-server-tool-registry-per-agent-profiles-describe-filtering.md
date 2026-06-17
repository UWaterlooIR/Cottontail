---
id: TASK-5.3
title: 'A0 — Engine/server: tool registry + per-agent profiles + /describe filtering'
status: To Do
assignee: []
created_date: '2026-06-17 15:51'
labels:
  - engine
  - cpp
  - server
  - searcher
dependencies: []
references:
  - docs/searcher-agent-lessons-June-16-2026.md
  - docs/cottontail-search-server-spec.md
  - docs/cottontail-jsonl-cli-spec.md
  - apps/cottontail-jsonl-server.cc
  - apps/jsonl_json.cc
  - apps/jsonl_json.h
  - test/jsonl_server.cc
  - CLAUDE.md
parent_task_id: TASK-5
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives (architecture)

C++ change in the JSONL search-tool layer + server. GCL core (`src/parse.cc`,
`src/gcl.h`) is NOT touched. Likely files: a small new registry in
`apps/jsonl_json.{h,cc}` and/or a new `apps/tool_registry.{h,cc}`,
`apps/cottontail-jsonl-server.cc`, `apps/cottontail-jsonl-query.cc`; tests in
`test/jsonl_server.cc`; docs `docs/cottontail-search-server-spec.md`.

## Why (the platform idea)

The CLI and HTTP/JSON server are a PLATFORM that will host MANY search tools, and
different agents need different SUBSETS. In LLM tool-calling, the `tools` array passed
with the prompt IS the selection — so "agent = prompt + a chosen set of tools." Today
all tools are exposed and `GET /describe` (describe_json) returns everything in one list.
A0 makes exposure declarative so today's ISJ agent and future agents each get a tailored
toolset without cross-contamination. This unblocks keeping the raw `search_gcl` (pure
GCL) separate from the new ISJ `cover_search` (A1/A2): they live in different profiles.

## Required behavior (the contract)

1. Tool registry. Introduce a registry mapping a unique tool NAME -> { request/response
   JSON schema (for /describe), handler over jsonl_core }. Register the existing engine
   tools through it: search_text, search_gcl, count_matches, explain, get_document. No
   change to any tool's own request/response contract (no drift).
2. Profiles. A profile is a NAMED set of tool names, declared in ONE place (a code
   constant or small config), e.g.:
     - "gcl"  = { search_gcl, search_text, count_matches, explain, get_document }  (raw GCL primitives)
     - "isj"  = { get_document }   (cover_search is added to this profile by A1)
   Keep it lightweight — a name->list map, NOT a plugin framework or per-tool auth system.
3. Profile-aware discovery. `GET /describe?profile=<name>` returns only that profile's
   tool schemas; an unknown profile is a clear 400. Define and document the no-argument
   default (recommend: return all registered tools, or a configured default profile).
4. Profiles govern DISCOVERY, not access. `POST /tools/<name>` still works for every
   registered tool; profiles curate what an agent is TOLD about via /describe. (Hard
   per-tool access control is a deliberate non-goal — out of scope, future if needed.)
5. Agent = prompt + profile. Document this model and a short "how to add a new tool and
   expose it to an agent" recipe, so future tools/agents are additive.

Optional (nice, not required): allow a profile to present a tool under an agent-facing
display name (e.g. get_document shown as `read` in the isj profile). If it adds
machinery, skip it and keep get_document.

## Non-goals

- Do NOT modify the GCL core/engine.
- Do NOT create cover_search or any new search behavior (that is A1/A2). A0 only adds the
  registry/profile machinery and migrates the EXISTING tools into it.
- Do NOT add per-tool authentication/authorization (only the existing bearer-token server
  auth stays as-is). Profiles are discovery curation, not security.
- Do NOT change any existing tool's own JSON request/response shape.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A tool registry maps each unique tool name to its schema and handler; the existing tools (search_text, search_gcl, count_matches, explain, get_document) are registered through it and the server routes POST /tools/<name> and /describe from the registry.
- [ ] #2 Profiles are declared in one place as named sets of tool names; at least gcl = {search_gcl, search_text, count_matches, explain, get_document} and isj = {get_document} (cover_search joins isj in A1).
- [ ] #3 GET /describe?profile=isj returns only the isj profile's tool schemas; ?profile=gcl returns the gcl set; an unknown profile returns a clear 400; the no-profile default is defined and documented.
- [ ] #4 Profiles govern discovery only: POST /tools/<name> still works for a registered tool even if it is not in the queried profile (verified by a test).
- [ ] #5 No existing tool's own request/response JSON shape changes (no contract drift).
- [ ] #6 docs/cottontail-search-server-spec.md documents the registry, the gcl and isj profiles, the agent = prompt + profile model, and a recipe for adding a new tool and exposing it to an agent.
- [ ] #7 bazel test //test:tests //test:hazel_test //test:jsonl_test is green, with server tests covering /describe profile filtering and discovery-vs-access.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Read apps/cottontail-jsonl-server.cc (the svr.Post("/tools/<name>", ...) wiring and
   the /describe handler) and apps/jsonl_json.cc (describe_json()).
2. Add a registry: a name -> {schema, handler} table. Register search_text, search_gcl,
   count_matches, explain, get_document. Drive the server's POST /tools/<name> routing
   and /describe from the registry (single source of truth).
3. Add profiles as a declared name->{tool names} map: "gcl" and "isj" (isj = {get_document}
   for now). Put it in one obvious place.
4. Make describe_json profile-aware: describe_json(profile) returns only that profile's
   tool schemas; GET /describe?profile=<name> uses it; unknown profile -> 400; document
   the default (no profile).
5. Server stays stateless and keeps its existing bearer-token auth. CLI: if useful, a
   --describe --profile <name> flag mirrors the server.
6. Docs: docs/cottontail-search-server-spec.md — document the registry, the two profiles,
   the agent=prompt+profile model, and a recipe for adding a tool + exposing it.
7. Tests: test/jsonl_server.cc — /describe?profile=isj returns only the isj set,
   ?profile=gcl returns the gcl set, unknown profile 400, and POST /tools/<name> still
   works for a tool not in the queried profile (discovery vs access).

Build (per CLAUDE.md): bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
Test: bazel test //test:tests //test:hazel_test //test:jsonl_test (plus the server test target).
<!-- SECTION:PLAN:END -->
