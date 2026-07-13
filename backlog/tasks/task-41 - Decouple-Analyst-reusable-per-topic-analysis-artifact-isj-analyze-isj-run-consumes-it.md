---
id: TASK-41
title: >-
  Decouple Analyst: reusable per-topic analysis artifact + isj analyze + isj-run
  consumes it
status: To Do
assignee: []
created_date: '2026-07-13 17:46'
updated_date: '2026-07-13 17:50'
labels:
  - analyst
  - isj
dependencies: []
ordinal: 58000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make the Analyst output a first-class, reusable artifact so one analysis per topic drives every searcher-agent run, factoring analyst variation out of cross-searcher comparisons. Plumbing is analyst-agnostic (works with today's Analyst and the future ReportAnalyst).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj analyze runs a configured Analyst over a topics TSV and writes one self-contained artifact per topic: <out>/<topic_id>.json = {topic_id, question, interpretations[], analyst{class,prompt,model,reasoning,temperature}}, plus an analysis.meta.json (provenance: analyst config, topics file). Resumable (skips existing).
- [ ] #2 isj run accepts --analysis-file <report.json> as an alternative to --question; when given it loads the artifact, uses its question + interpretations, and SKIPS the Analyst entirely (orchestrator.run_question gains an optional intents param). --question keeps today's built-in-Analyst behavior.
- [ ] #3 run_topics_cycled can pass --analysis-file <analysis-dir>/<topic>.json per topic so gcl/mt/lucindri all consume the identical analysis.
- [ ] #4 Tests cover artifact write/read round-trip and that an isj run from --analysis-file makes no Analyst LLM call; isj suite green.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: Make the Analyst output a reusable per-topic ARTIFACT so ONE analysis drives every
searcher-agent run (gcl/mt/lucindri), factoring analyst variation out of cross-searcher
comparisons. Analyst-agnostic: works with today's Analyst AND the future ReportAnalyst
(TASK-42). Work on branch claude/analyst-report-scout.

KEY CURRENT FACTS (verified):
- isj/isj_agent/orchestrator.py: Orchestrator.__init__(self, analyst, controller, *, max_judgments=1000).
  run_question(self, question, *, on_intent=None, observer=None, on_analyzed=None) ->
  (intents, outcomes, run_error). It calls `intents = self.analyst.analyze(question)` (line ~57),
  fires on_analyzed(intents), then loops controller.run(interp, intent_budget, observer=obs) per
  interpretation. intent_budget = max(1, max_judgments // len(intents.interpretations)).
- isj/isj_agent/protocol/intents.py: Intents(BaseModel){question:str; interpretations:list[str] Field(min_length=1)}.
- isj/isj_agent/agents/analyst.py: Analyst.__init__(client, model, *, reasoning_effort='medium',
  temperature=0.0, max_tokens=8000, timeout_s=120.0). prompt = class attr _PROMPT (analyst.md).
  analyze(question)->Intents via response_format json_schema built from Intents.model_json_schema()
  (so the Intents docstring is sent to vLLM). Base Analyst.__init__ has NO `prompt` param.
- isj/isj_agent/config.py: load_class(dotted), build_client(llm_cfg)->openai.OpenAI,
  build_coach(config, clients, llm_configs)->(coach,mechanical), resolve_context_limit(...).
  NO build_analyst yet.
- isj/isj_agent/cli.py: builds clients={name:build_client(cfg)}; _build_agent(role,**extra) does
  load_class(cfg['class'])(client=clients[cfg['llm']], model=llm_configs[cfg['llm']]['model'], **extra);
  builds analyst with kwargs {reasoning_effort,temperature,max_tokens,timeout_s}; then
  orchestrator.run_question(args.question, on_analyzed=writer.start, observer=writer.observe,
  on_intent=writer.finish_intent). writer=StreamingRunWriter(out,...); writer.start(intents) writes intents.json.

STEPS:
1. NEW isj_agent/analysis.py (small helpers, no engine deps):
   - ARTIFACT shape (on disk, one file per topic <out>/<topic_id>.json):
     {"topic_id": str, "question": str, "interpretations": [str,...],
      "analyst": {"class": dotted, "model": str, "reasoning_effort": str, "temperature": float}}
   - write_report(out_dir: Path, topic_id: str, intents: Intents, analyst_meta: dict) -> Path:
     data = {"topic_id":topic_id, "question":intents.question,
             "interpretations":intents.interpretations, "analyst":analyst_meta};
     p = out_dir/f'{topic_id}.json'; p.write_text(json.dumps(data, indent=2, ensure_ascii=False)); return p
   - load_report(path: Path) -> tuple[str, Intents]:
     d=json.loads(path.read_text()); return d['topic_id'], Intents(question=d['question'],
       interpretations=d['interpretations'])   # Intents validates min_length>=1

2. config.build_analyst(config, clients, llm_configs) -> Analyst  (mirror _build_agent + build_coach):
     cfg=config['agents']['analyst']; cls=load_class(cfg['class']);
     kw={k:cfg[k] for k in ('reasoning_effort','temperature','max_tokens','timeout_s') if k in cfg}
     return cls(client=clients[cfg['llm']], model=llm_configs[cfg['llm']]['model'], **kw)
   Do NOT pass 'prompt' (base Analyst has no such param; ReportAnalyst bundles its own).
   Also add analyst_meta(config, llm_configs) -> dict helper OR compute meta in analyze_cli:
     a=config['agents']['analyst']; meta={'class':a['class'], 'model':llm_configs[a['llm']]['model'],
       'reasoning_effort':a.get('reasoning_effort','medium'), 'temperature':a.get('temperature',0.0)}

3. NEW isj_agent/analyze_cli.py  (python -m isj_agent.analyze):
   argparse: --topics(Path,req), --out(Path,req), --config(Path, default Path(__file__).parent.parent/'config.toml'),
     --only(action=append,default=[]), --limit(int), --overwrite(store_true).
   - load config via tomllib; llm_configs=config['llm']; clients={n:build_client(c)}.
   - analyst=build_analyst(config,clients,llm_configs); meta=<analyst_meta above>.
   - read_topics(tsv): csv.reader delim='\t'; rows with >=2 cols and row[0].strip() -> (id, row[1]).
     (copy the read_topics pattern from trec-rag-2026 scripts/run_topics.py.)
   - filter by --only / --limit.
   - out.mkdir(parents=True, exist_ok=True); write out/'analysis.meta.json' =
     {'analyst':meta, 'topics_file':str(topics), 'config':str(config)}.
   - for (id,q): dest=out/f'{id}.json'; if dest.exists() and not --overwrite: print SKIP; continue;
     intents=analyst.analyze(q); write_report(out,id,intents,meta); print ok.
   - Needs only vLLM. Resumable via the skip.

4. orchestrator.run_question: add keyword param intents: Intents|None=None (place after `question`).
   Body: `if intents is None: try: intents=self.analyst.analyze(question) except Exception as exc:
   return None,[],f'analysis failed: ...'`. Keep on_analyzed(intents) + the loop unchanged.
   Orchestrator.__init__ analyst type -> Analyst|None=None (analyst unused when intents supplied).

5. isj cli.py:
   - Replace `--question required` with a mutually-exclusive REQUIRED group:
     g=parser.add_mutually_exclusive_group(required=True); g.add_argument('--question');
     g.add_argument('--analysis-file', type=Path, help='precomputed analysis JSON (skips the Analyst)').
   - If args.analysis_file: from isj_agent.analysis import load_report; topic_id,intents=load_report(args.analysis_file);
     question=intents.question; analyst=None (do NOT build it).
     else: question=args.question; intents=None; analyst=_build_agent('analyst',...) (as today).
   - orchestrator=Orchestrator(analyst, controller, max_judgments=...);
     orchestrator.run_question(question, intents=intents, on_analyzed=writer.start, observer=..., on_intent=...).
   - Everything else (engine/coach/controller build) unchanged; those are always needed.

6. TESTS (isj/tests/):
   - test_analysis.py: write_report then load_report round-trips {topic_id,question,interpretations};
     provenance persisted; Intents validates.
   - orchestrator: add a test that run_question(question, intents=Intents(question='q',interpretations=['a','b']))
     does NOT call analyst.analyze (stub analyst.analyze raises) and returns outcomes for both interps
     (reuse existing orchestrator test stubs/controller).
   Run `uv run pytest` -> green.

NOTE (trec-rag-2026, follow-up, NOT this task): run_topics_cycled.py will switch the per-topic isj
invocation from `--question <q>` to `--analysis-file <analysis-dir>/<topic>.json`, and a one-time
`python -m isj_agent.analyze --topics <tsv> --config <analyst-cfg> --out <analysis-dir>` produces the
analysis dir. That wiring lives in trec-rag-2026.

GOTCHAS: base Analyst has no prompt param; keep --question path fully working (smoke tests use it);
on_analyzed must still fire in --analysis-file mode (writes intents.json); interpretations feed the
Controller unchanged as list[str]; use add_mutually_exclusive_group(required=True).
<!-- SECTION:PLAN:END -->
