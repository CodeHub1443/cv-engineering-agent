# ADR-0000: <Title>

- **Status:** Proposed | Accepted | Superseded by ADR-XXXX | Rejected
- **Date:** YYYY-MM-DD
- **Layer:** reasoning | orchestration | knowledge | execution | memory | cross-cutting
- **Canon:** `[P§n]`, `[P§m]`
- **Supersedes / Superseded by:** —
- **Issue:** #

## 1. Context

What forces make this decision necessary now? What is currently true in the repo?
Cite the canon sections that constrain the choice.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** one sentence.
- **This does NOT own:** list, and for each, name the layer that does own it.
- **Why this responsibility does not belong to an existing component:**

> If this section cannot be completed cleanly, the boundary is wrong. Stop and redesign
> rather than writing the ADR.

## 3. Decision

The choice, stated in the active voice. One paragraph.

## 4. Alternatives considered

Minimum three, each with **evidence**, not intuition `[P§29.3]`. Where evidence depends
on current information, cite sources with dates and source class per
`docs/RESEARCH_POLICY.md`.

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| | | | |

## 5. Interface

Types and signatures only. **No implementation bodies in an ADR.**

```python
# module: cv_agent.<...>
```

## 6. Consequences

- **Enables:**
- **Makes harder:**
- **Costs (build, runtime, GPU, $):**
- **Migration / blast radius if reversed:**

## 7. Acceptance test

The concrete, runnable test that proves this subsystem does what it claims. Named test
file and assertion, not a description of a feeling.

## 8. Revisit trigger

What observation would make us reopen this decision? (A benchmark result, a provider
change, a latency budget breach, a new release.) Without a trigger, this ADR is a guess
with no expiry.
