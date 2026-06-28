# Designing Deep Research Report Agents: Architecture and Orchestration

*A synthesized review of the research literature and system write-ups on how to design
"Deep Research" agents — LLM systems that autonomously plan, search and browse many
sources, reason over multiple steps, and produce a synthesized, cited report. The emphasis
here is on **system architecture and components** and on **multi-agent orchestration**;
training methods and benchmarks appear only where they shape design.*

---

## 1. Scope and definition

A working definition has converged across the recent surveys. A Deep Research (DR) agent is
an LLM-driven system that integrates dynamic reasoning, adaptive planning, and iterative
tool use to acquire, aggregate, and analyze external information, culminating in a
comprehensive report for an open-ended informational task (Huang et al., 2025, arXiv:2506.18096).
This is the property that separates a DR agent from classic retrieval-augmented generation
(RAG): RAG performs a static fetch-then-generate pass, whereas a DR agent runs a *dynamic,
multi-turn loop* in which what it finds reshapes what it does next (Anthropic, 2025; JMIR
Viewpoint, 2026, doi:10.2196/88195).

The category crystallized in 2025 with the near-simultaneous launch of OpenAI Deep Research,
Google's Gemini Deep Research, Perplexity Deep Research, and Anthropic's Claude Research,
followed by a wave of academic surveys (Huang et al., 2025; Xi et al., 2025, arXiv:2508.05668;
Shi et al., 2025, arXiv:2512.02038). This report concentrates on the two design dimensions the
brief prioritized — component architecture and orchestration — and treats reinforcement-learning
training and benchmark construction as supporting context.

A useful framing throughout: the same iterative ideas that the information-science literature
identified in human expert searchers — an evolving query, search-as-compression, navigate-then-
reformulate, and a diminishing-returns stopping rule — are exactly what these agents
re-implement in software. The architecture below is, in effect, an automation of that loop.

---

## 2. The reference architecture

Across systems, the pipeline is strikingly convergent. Most DR agents instantiate some subset
of the following stages:

1. **(Optional) intent clarification** — ask a few targeted follow-up questions when the request
   is short or ambiguous (OpenAI, 2025; the open-source Onyx system asks up to ~5).
2. **Planning / decomposition** — turn the request into a research brief or plan and break it into
   sub-questions or exploration directions.
3. **Iterative research loop** — repeatedly: formulate a query, search and/or browse, read and
   extract evidence, reflect on gaps and contradictions, and decide what to do next.
4. **Synthesis** — organize findings, usually outline-first, into a long-form structured report.
5. **Citation / attribution** — bind claims to sources, often as a distinct verification pass.

This loop has a clear lineage. **WebGPT** (Nakano et al., 2021, arXiv:2112.09332) first fine-tuned
a model to operate a text browser — issuing search, follow-link, and quote commands and citing
its sources so that factual accuracy could be checked. **ReAct** (Yao et al., 2023, ICLR;
arXiv:2210.03629) established the reason→act→observe interleaving that is the heartbeat of every
DR agent. **Reflexion** (Shinn et al., 2023, NeurIPS; arXiv:2303.11366) added verbal self-reflection
over trials, the basis for the "identify gaps and retry" behavior. Later component techniques —
Self-Refine, Plan-and-Solve, Tree-of-Thoughts — fill out the same toolbox. DR agents are best
understood as these primitives assembled into a long-horizon, report-producing whole.

---

## 3. Component design (architecture)

### 3.1 Information acquisition: API search vs. browser

Surveys split acquisition into **API-based retrieval** (calling a search engine or structured
index) and **browser-based exploration** (navigating live pages like a person) (Huang et al.,
2025). API retrieval is faster and more controllable; browsing reaches content that search APIs
miss and supports following links, but is slower and noisier. Production systems often combine
them — e.g., Perplexity pairs an index (Bing-style, with BM25 plus dense reranking via its Sonar
API) with iterative reading (Step-DeepResearch report, 2025, arXiv:2512.20491). The acquisition
step is *iterative and multi-hop*: the agent issues a query, reads results, then issues new
queries informed by what it learned, rather than retrieving once. This is where classic query-
reformulation tactics (generalize, specialize, substitute terms, pearl-grow from a good hit)
matter, and several systems learn these via RL (Search-R1, DeepResearcher, ReSearch; see §4 and
Shi et al., 2025).

### 3.2 Planning and task decomposition

Planning is the most studied component. Two design choices dominate.

**Static vs. dynamic workflows.** A static workflow fixes the pipeline in advance; a dynamic one
lets the agent re-plan mid-task as evidence arrives (Huang et al., 2025). DR agents lean dynamic —
OpenAI describes a "dynamically adaptive iterative research workflow" that refines strategy during
execution (Huang et al., 2025, §4), and Gemini exposes an editable multi-step plan ("research
blueprint") that it revises as it goes (Google DeepMind, 2025).

**Decompose into sub-questions / facets.** The planner explodes the request into the handful of
sub-questions that jointly answer it. A recurring and deliberate design constraint is to give the
*planner no tool access* so that it produces a plan, not premature answers (observed in the
open-source Onyx system, which decomposes into up to ~6 directions). LangChain's Open Deep Research
ships an explicit **plan-and-execute** variant in which a human can review the section plan before
research runs (LangChain, 2025).

**Clarification first.** Many systems insert an interactive clarification step before planning, to
pin down intent (OpenAI, 2025; Gemini's user-reviewable plan serves a similar role). This is cheap
and materially improves downstream relevance.

### 3.3 The reasoning loop and reflection

The core loop is ReAct-style action selection wrapped in a reflective controller. After each
search-and-read cycle, the agent grounds itself on everything gathered so far, then identifies
missing information and discrepancies to explore next — Gemini's documentation describes exactly
this gap-and-discrepancy step (Google DeepMind, 2025), and LangChain's framework identifies
knowledge gaps via self-reflection before deciding to continue (Step-DeepResearch report, 2025).
Reflexion-style verbal feedback (Shinn et al., 2023) and self-critique loops (a ReAct agent with
Reflexion is a common "Search Agent" recipe; ReST-meets-ReAct, 2023, arXiv:2312.10003) underpin the
"keep going until the plan is satisfied" behavior — and, crucially, the *stopping* behavior, which
is a frequent failure point (agents that search endlessly or quit too early; Anthropic, 2025).

### 3.4 Tool use and extensibility

Beyond search/browse, the standard toolset includes **code execution** (a Python tool for data
analysis and computation — OpenAI Deep Research ships one) and **multimodal input** (reading PDFs,
images, charts). The emerging extensibility mechanism is the **Model Context Protocol (MCP)**,
which lets an agent plug in arbitrary external tools and data sources through a common interface;
the surveys highlight MCP as the basis for an ecosystem, and open frameworks (LangChain Open Deep
Research; GPT-Researcher) advertise native MCP support (Huang et al., 2025; LangChain, 2025).
Anthropic even built a tool-testing agent that rewrites flawed tool descriptions to reduce
downstream tool-selection errors (Anthropic, 2025).

### 3.5 Memory and context management

Long research runs exhaust the context window, so memory is a first-class design concern. Tactics
in use: **compression / summarization** of intermediate findings before passing them upward;
**separate context windows** per worker so that exploration of different sub-topics does not crowd
a single window; **persistent state** that survives context limits (Anthropic's lead agent persists
its plan and findings past ~200K tokens); and **asynchronous shared state** between planner and
workers for fault tolerance (Gemini's "asynchronous task manager" lets a single failed step recover
without restarting the whole task) (Anthropic, 2025; Google DeepMind, 2025). The umbrella practice
is **context engineering** — dynamically curating exactly the right information into each model
call — which both Anthropic and Cognition independently single out as the central reliability lever
(Anthropic, 2025; Cognition, 2025; Prompting Guide, 2026). A maturing literature on agent memory
patterns (buffer → episodic → semantic → procedural → graph) and systems like Mem0 sits behind this.

### 3.6 Synthesis and report generation

Producing a long, grounded report is its own problem, distinct from gathering the evidence. The
canonical academic system is **STORM** (Shao et al., 2024, NAACL; arXiv:2402.14207), which splits
the task into a *pre-writing* stage (research → outline) and a *writing* stage (outline +
references → cited article). Its key idea is **perspective-guided question asking**: rather than
prompting a model to "ask questions," STORM mines distinct perspectives from related articles and
runs *simulated conversations* between a writer persona and a source-grounded expert to elicit
deeper follow-up questions. **Co-STORM** (Jiang et al., 2024, EMNLP) extends this with a multi-agent
discourse protocol, a turn-management policy, and a shared dynamic mind map for human-in-the-loop
curation. The outline-first pattern recurs in production frameworks (GPT-Researcher's
planner→executor→**publisher**; LangChain's compression→final-report stages).

Two synthesis-specific concerns deserve design attention:

- **Citation grounding / faithfulness.** Reports must attribute claims to sources. Anthropic runs a
  dedicated **CitationAgent** as a final pass that maps each claim to its supporting document
  (Anthropic, 2025); STORM measures citation recall and precision. But attribution is not truth:
  benchmarks that check whether a citation *supports* a claim do not verify the claim is *correct*,
  so an agent can be well-cited and still wrong if it trusts an unreliable source (DeepResearch
  Bench II, 2026, arXiv:2601.08536).
- **Conflict resolution.** When sources contradict, the agent must reconcile them rather than
  averaging or picking arbitrarily — a recognized open problem with early methods (fact-level
  conflict modeling, inter-source conflict detection) surveyed in Deep Research: A Survey of
  Autonomous Research Agents (2025, arXiv:2508.12752).

---

## 4. Orchestration design (single-agent vs. multi-agent)

This is the most consequential — and most contested — architectural decision for a DR agent.

### 4.1 The central axis

**Single-agent, end-to-end.** OpenAI Deep Research is a *single* agent: an o3 reasoning model
fine-tuned with end-to-end reinforcement learning on hard browsing and reasoning tasks, with
browser and Python tools, that learned to plan multi-step trajectories, backtrack from dead ends,
and pivot on new information (OpenAI, 2025; Sequoia "Training Data" interview with Fulford & Tobin,
2025; Huang et al., 2025 classify it as single-agent). The architecture *is* the model: capability
comes from training, not from an external multi-agent scaffold. The open-source RL line —
Search-R1, DeepResearcher, ReSearch, and survey RL Foundations for Deep Research Systems
(2025, arXiv:2509.06733) — pursues the same single-policy philosophy.

**Multi-agent, orchestrated.** Anthropic's Claude Research is a *multi-agent* system built on an
**orchestrator-worker** pattern: a lead agent analyzes the query, devises a strategy, and spawns
specialized subagents that search in parallel, each with its own context window, tools, and task
boundaries; the lead synthesizes their compressed findings and decides whether to spawn more; a
separate CitationAgent then attributes the claims (Anthropic, 2025). Anthropic frames search as
*compression* and argues subagents enable scaling that a single context window cannot: they report
a multi-agent system (Opus 4 lead + Sonnet 4 subagents) outperforming single-agent Opus 4 by 90.2%
on an internal research eval — at roughly 15× the token cost of a chat (Anthropic, 2025).

### 4.2 Multi-agent topologies

When you do go multi-agent, the topology is the key choice (Anthropic, 2025; Philschmid, 2025):

- **Orchestrator-worker / supervisor.** A central agent plans and delegates; workers do not talk to
  each other; every routing decision lives in the orchestrator. This constrains the interaction
  graph and makes the system easier to reason about. (Anthropic's Research; LangChain Open Deep
  Research's supervisor → parallel researchers, with configurable concurrency; GPT-Researcher's
  multi-agent "chief editor / editor / researcher / reviewer / writer / publisher" team, explicitly
  inspired by STORM.)
- **Swarm / peer-to-peer.** Agents communicate directly and share state via a message bus or shared
  scratchpad. More flexible, but harder to reason about and more failure-prone.

Anthropic names the decisive variable the **isolation boundary**: how much each subagent needs to
know about what the others are doing. For breadth-first research their bet is "almost nothing" —
each subagent receives a self-contained objective, an output format, tool/source guidance, clear
boundaries, and a fresh context window (Anthropic, 2025).

### 4.3 The case against multi-agent

Cognition's "Don't Build Multi-Agents" (Walden Yan, 2025) is the influential counterargument.
Its claim: reliability over long horizons depends on every actor sharing the full context and
trace, because *actions carry implicit decisions, and conflicting implicit decisions produce
incoherent results*. Subagents working from partial views make conflicting assumptions that only
surface when their outputs are combined. Cognition's prescription is single-threaded agents plus
rigorous **context engineering**, not parallel agents.

Empirical work supports caution: the **MAST** failure taxonomy ("Why Do Multi-Agent LLM Systems
Fail?", Cemri et al., 2025) attributes a large share of multi-agent failures to inter-agent
misalignment — a failure mode that simply cannot occur in a single agent. Reported multi-agent
failure rates across systems are high.

### 4.4 Reconciling the debate — read vs. write

The two camps agree more than the titles suggest, and the reconciliation is the practical design
rule (Philschmid, 2025; Vellum, 2025):

- The real question is not single vs. multi but **read vs. write**. *Read-heavy* work (research,
  information gathering, analysis) parallelizes cleanly — independent subagents explore different
  sub-topics and their results aggregate easily, which is exactly DR's sweet spot. *Write-heavy*
  work (code, a single coherent artifact) creates coordination conflicts when split, favoring a
  single agent. Mixed tasks should separate the read and write phases architecturally.
- **Both sides agree context engineering is the core reliability mechanism.** Whether you isolate
  subagents (Anthropic) or keep one thread (Cognition), what determines success is getting the right
  context to the right model call.
- **Default to the simplest thing that works.** A common recommendation is to start single-agent and
  escalate to multi-agent only after proving value and identifying a genuine need for parallelism or
  specialization, because multi-agent systems are costlier and harder to debug (Vellum, 2025).

For a DR *report* agent specifically — a breadth-first, read-dominated task whose sub-questions are
largely independent and whose final write step is a single synthesis — this analysis points toward
**parallel research workers feeding a single synthesizer**, which is precisely the shape that
Anthropic's Research, GPT-Researcher's multi-agent mode, LangChain's supervisor variant, and Onyx
all converge on.

---

## 5. Industry and open-source landscape

The major systems differ mainly in orchestration, sync/async execution, and openness:

- **OpenAI Deep Research** — single agent; RL-fine-tuned o3; browser + Python; clarification step;
  dynamic iterative workflow (OpenAI, 2025).
- **Gemini Deep Research** — iterative multi-step planner with a *user-editable* research plan;
  asynchronous task manager with shared planner/worker state for fault tolerance; very long context;
  background ("set it and come back") execution (Google DeepMind, 2025).
- **Perplexity Deep Research** — fast iterative search-read-reason loop over an index (BM25 + dense
  reranking) plus reasoning and code; synthesizes after evaluating sources; emphasizes speed and
  sentence-level citation (Perplexity, 2025).
- **Claude Research (Anthropic)** — multi-agent orchestrator-worker with parallel subagents and a
  separate citation pass; tuned for breadth-first research (Anthropic, 2025).
- **Open-source frameworks** — **GPT-Researcher** (planner→parallel executors→publisher, plus a
  STORM-inspired multi-agent mode); **LangChain Open Deep Research** (LangGraph state machine;
  supervisor↔researchers with configurable concurrency; ships plan-and-execute and supervisor
  topologies; MCP-compatible); **Onyx** (clarify → tool-less planner → orchestrator + parallel
  research agents over up to ~8 cycles; reported #1 on DeepResearch Bench); **Open Deep Search**
  (Alzubi et al., 2025, arXiv:2503.20201) and **Tongyi DeepResearch** (Alibaba) on the open RL side.

A practical note from these write-ups: observability and durable execution (tracing every agent
interaction, surviving mid-run failures) separate a demo from a production system, and frameworks
increasingly bundle this (e.g., LangSmith tracing, LangGraph checkpointing).

---

## 6. Cross-cutting design concerns

- **Cost and token economics.** Multi-agent breadth costs ~15× a chat turn; performance gains track
  token spend ("multi-agent works largely because it spends enough tokens"), so DR agents are
  justified only when answer value outweighs cost, and runaway subagent spawning must be capped in
  the orchestration layer, not merely requested in a prompt (Anthropic, 2025).
- **Latency and fault tolerance.** Long multi-call runs need asynchronous execution and graceful
  recovery so one failed step doesn't restart the task (Gemini's async task manager; Anthropic's
  persistent state) (Google DeepMind, 2025; Anthropic, 2025).
- **Effort scaling.** Match compute to task difficulty — embed explicit rules (e.g., one worker for
  simple fact-finding, a few for comparisons, many for complex research) rather than letting the
  agent over- or under-allocate (Anthropic, 2025).
- **Human oversight.** Editable plans (Gemini), human-reviewable section plans (LangChain
  plan-and-execute), and collaborative curation (Co-STORM) all insert review at the cheapest,
  highest-leverage point — the plan, before expensive research runs.
- **Faithfulness and source reliability.** Citations lend "an air of authority" that can mask basic
  errors, and a capable model may cherry-pick convincing-but-unrepresentative sources — a risk
  flagged as far back as WebGPT (Nakano et al., 2021) and unresolved by citation-support metrics
  (DeepResearch Bench II, 2026).
- **Safety and security.** Two distinct issues. (1) **Indirect prompt injection**: a browsing agent
  ingests web content as ordinary tokens with no instruction/data channel separation, so hidden
  instructions in a page can hijack it — and "ignore instructions in external content" is not a
  reliable defense (Greshake et al., 2023, arXiv:2302.12173; documented in-the-wild in 2026). (2)
  **Pipeline-level misalignment**: multi-step research framing can weaken the refusal behavior that
  protects a standalone LLM; "Plan Injection" and "Intent Hijack" attacks elicit credible-but-harmful
  reports, motivating alignment and evaluation across the whole reasoning loop, not just the final
  answer (Deep Research Brings Deeper Harm, 2025, arXiv:2510.11851; JMIR Viewpoint, 2026).

---

## 7. Evaluation (brief)

Two evaluation families inform design. **Close-ended** benchmarks test whether the agent can find a
fixed answer: **GAIA** (Mialon et al., 2023, arXiv:2311.12983) for general tool-use/reasoning,
**BrowseComp** (Wei et al., 2025) for persistent browsing, **Humanity's Last Exam** and **Mind2Web 2**
(Gou et al., 2025, arXiv:2506.21506, with an Agent-as-a-Judge protocol). **Open-ended** benchmarks
judge report quality directly: **DeepResearch Bench** (Du et al., 2025, arXiv:2506.11763) — 100
PhD-level tasks across 22 fields, with **RACE** scoring report quality (comprehensiveness, insight,
instruction-following, readability) and **FACT** scoring effective citation count and accuracy. The
caveat above bears repeating for designers: these citation metrics check support, not correctness.

---

## 8. Design takeaways and open problems

Synthesizing across the sources, a defensible default architecture for a DR *report* agent is:
**clarify intent → produce a (preferably human-reviewable) plan with a tool-less planner → run an
iterative loop of parallel read-only research workers, each isolated with its own context, that
search/browse, extract, and reflect on gaps → compress findings → synthesize outline-first into a
report → verify and attach citations in a dedicated pass**, with context engineering, effort caps,
async fault tolerance, and prompt-injection defenses treated as first-class, not afterthoughts.

Open problems the literature flags: brittle plans under ambiguous goals; reconciling contradictory
sources; faithfulness beyond mere citation support; reliable stopping (knowing when enough is
enough); the cost/quality frontier of multi-agent breadth; and safety across the full loop. These
are where current research is concentrated.

---

## 9. Coverage note (limits of this search)

This review combined recall passes (canonical systems and authors) with discovery passes
(goal-phrased queries, recency sweeps to 2026, cross-field vocabulary, and citation traversal from
the central surveys). Across those passes, **no architectural family appeared for DR report agents
beyond the plan → iterative search/read/reflect → synthesize → cite loop and its single-agent
(end-to-end RL) versus multi-agent (orchestrated) realizations.** Two areas were intentionally
under-weighted per the brief and are noted but not developed: RL/fine-tuning *training* methods
(the single-agent path's engine — Search-R1, DeepResearcher, and the RL-foundations survey) and
deep *benchmark* construction. If either should be expanded, that is a clean next pass.

---

## References

**Surveys**
- Huang, Y., Chen, Y., Zhang, H., et al. (2025). *Deep Research Agents: A Systematic Examination and Roadmap.* arXiv:2506.18096.
- Xi, Y., et al. (2025). *A Survey of LLM-based Deep Search Agents: Paradigm, Optimization, Evaluation, and Challenges.* arXiv:2508.05668.
- *Deep Research: A Survey of Autonomous Research Agents.* (2025). arXiv:2508.12752.
- Shi, Z., et al. (2025). *Deep Research: A Systematic Survey.* arXiv:2512.02038.
- *Reinforcement Learning Foundations for Deep Research Systems: A Survey.* (2025). arXiv:2509.06733.

**Foundational components**
- Nakano, R., et al. (2021). *WebGPT: Browser-assisted Question-answering with Human Feedback.* arXiv:2112.09332.
- Yao, S., et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023. arXiv:2210.03629.
- Shinn, N., et al. (2023). *Reflexion: Language Agents with Verbal Reinforcement Learning.* NeurIPS 2023. arXiv:2303.11366.

**Report generation**
- Shao, Y., et al. (2024). *Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models* (STORM). NAACL 2024. arXiv:2402.14207.
- Jiang, Y., et al. (2024). *Co-STORM: Collaborative knowledge curation through human–AI discourse.* EMNLP 2024.

**Industry systems**
- OpenAI (2025). *Introducing deep research.* https://openai.com/index/introducing-deep-research/
- Google DeepMind (2025). *Gemini Deep Research.* https://gemini.google/overview/deep-research/
- Perplexity (2025). *Introducing Perplexity Deep Research.* https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research
- Anthropic (2025). *How we built our multi-agent research system.* https://www.anthropic.com/engineering/multi-agent-research-system

**Orchestration**
- Yan, W. / Cognition (2025). *Don't Build Multi-Agents.* https://cognition.com/blog/dont-build-multi-agents
- Cemri, M., et al. (2025). *Why Do Multi-Agent LLM Systems Fail?* (MAST taxonomy). arXiv.

**Open-source frameworks**
- GPT-Researcher (Elovic et al.). https://github.com/assafelovic/gpt-researcher
- LangChain (2025). *Open Deep Research.* https://github.com/langchain-ai/open_deep_research
- Alzubi, S., et al. (2025). *Open Deep Search: Democratizing Search with Open-source Reasoning Agents.* arXiv:2503.20201.

**Benchmarks**
- Du, M., Xu, B., Zhu, C., Wang, X., & Mao, Z. (2025). *DeepResearch Bench: A Comprehensive Benchmark for Deep Research Agents.* arXiv:2506.11763.
- Mialon, G., et al. (2023). *GAIA: A Benchmark for General AI Assistants.* arXiv:2311.12983.
- Wei, J., et al. (2025). *BrowseComp: A Simple Yet Challenging Benchmark for Browsing Agents.* OpenAI.
- Gou, B., et al. (2025). *Mind2Web 2: Evaluating Agentic Search with Agent-as-a-Judge.* arXiv:2506.21506.

**Safety and reliability**
- Greshake, K., et al. (2023). *More than You've Asked For: Novel Prompt Injection Threats to Application-Integrated LLMs.* arXiv:2302.12173.
- *Deep Research Brings Deeper Harm.* (2025). arXiv:2510.11851.
- *Deep Research Agents: Major Breakthrough or Incremental Step?* (2026). J Med Internet Res, doi:10.2196/88195.

**Engineering / context-engineering commentary** (non-archival)
- Philschmid (2025). *Single vs. Multi-Agent System?* · Vellum (2025). *Multi-agent systems with context engineering.* · Step-DeepResearch Technical Report (2025), arXiv:2512.20491 · DeepResearch Bench II (2026), arXiv:2601.08536.

*Note: a few very recent arXiv identifiers and the Cemri et al. (MAST) and Co-STORM entries should be
confirmed against the source before formal citation; details for fast-moving 2025–2026 work shift as
versions are revised.*
