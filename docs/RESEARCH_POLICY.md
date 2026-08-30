# RESEARCH POLICY

Derived from `[P§16]`, `[P§17]`, `[P§18]`, `[P§19]`, `[P§29.3]`, `[P§29.7]`.

> The agent's knowledge cannot be static — CV changes too quickly `[P§16]`. But this
> "does **not** mean indiscriminately ingesting everything" `[P§18]`.

## Two mechanisms, kept separate

- **Persistent knowledge** — CV engineering principles, architecture docs, project
  learnings, benchmark results, NVIDIA/model documentation, papers. Retrieval subsystem.
- **Live research** — anything that changes fast: model releases, framework versions,
  benchmarks, ecosystem news. Fetched on demand, never assumed from pretrained memory.

RAG provides knowledge; the LLM provides reasoning; they do not merge `[P§19]`.

## When the agent must research rather than answer from memory

- Any claim about *current* model availability, versions, or benchmark numbers.
- Any statement about a library's present API or behavior.
- Any "X is better than Y" comparison not backed by a run in `EXPERIMENTS.md`.
- Any NVIDIA/TensorRT/DeepStream/TAO/Jetson capability question `[P§15]`.
- Anything the agent is about to state confidently and cannot cite.

## Source classes and evidence weight `[P§17]`

They must **not** all receive the same weight.

| Class | Weight | Use for | Caution |
|---|---|---|---|
| Peer-reviewed research | high | method validity, theory | may not reflect deployment reality |
| Official documentation | high | API, versions, supported features | can lag the code |
| Official repository / release notes | high | actual current behavior | read the code, not just the README |
| Reputable benchmark with published method | high | comparison — **if** the method is reproducible | check hardware and settings match yours |
| Engineering blog (vendor or practitioner) | medium | deployment experience, gotchas | vendor blogs sell |
| Professional post (LinkedIn etc.) `[P§17]` | **signal, not evidence** | discovering that a technique or trick exists | unverified, unreproducible, often promotional |
| Community discussion (issues, forums, Reddit) | low–medium | failure modes, real-world friction | anecdote |
| Model zoo / leaderboard entry | medium | candidate discovery | leaderboard ≠ your data or your hardware |

**LinkedIn rule** `[P§17]`: practical CV knowledge genuinely lives there — implementation
tricks, deployment experience, failure cases. Treat it as a **pointer to something worth
verifying**, never as a citation supporting a decision. A LinkedIn post may motivate an
experiment; only the experiment justifies a decision.

## The research pipeline `[P§18]`

Every research action follows this, and records the result:

1. **Find** — targeted query, not a sweep.
2. **Relevance** — does this bear on the current decision? If not, discard; do not store.
3. **Credibility** — assign the source class above.
4. **Extract** — the specific claim, with its conditions (hardware, dataset, settings).
5. **Provenance** — URL, author/org, source class, date published, date accessed.
6. **Freshness** — a staleness horizon appropriate to the topic (framework versions: weeks;
   architecture families: months; fundamentals: years).
7. **Make available** — to the reasoning layer, with weight and provenance attached.

A stored item missing provenance or date is deleted, not kept.

## Standing watch list `[P§18]`

Roboflow · YOLO ecosystem · Hugging Face · NVIDIA (TensorRT, DeepStream, TAO, Jetson,
Model Optimizer) · relevant GitHub projects · CV papers · practitioner discussion.

Watching means *checking when a decision depends on it*, not ingesting continuously.

## Anti-patterns

- Citing a model as "state of the art" without a date and a benchmark condition.
- Storing a document because it was found, rather than because it answers something.
- Treating a vendor claim as a measurement `[P§29.3]`.
- Letting retrieval volume substitute for retrieval quality `[P§31]`.
- Answering an ecosystem question from pretrained memory and presenting it as current.
