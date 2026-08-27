# CV Engineering Agent — Knowledge and Research

**Version:** V1.0  
**Status:** Foundational specification

## Purpose

Provide grounded, current knowledge for CV engineering decisions while preserving provenance and freshness.

## Knowledge Planes

~~~text
Stable / Canonical Knowledge
          +
Current Technology Knowledge
          +
Live Research
          ↓
     Knowledge Layer
          ↓
   Hybrid Retrieval / Ranking
          ↓
      Agent Context
~~~

### Stable / Canonical

Includes durable CV fundamentals, validated internal decisions, project specifications, and established engineering knowledge.

### Current Technology

Includes versioned APIs, framework releases, model releases, hardware/software compatibility, vendor guidance, benchmarks and other information likely to become stale.

### Live Research

Includes new papers, repositories, releases, engineering work and practitioner discoveries relevant to the task.

## Source Hierarchy

Prefer evidence in this order:

1. official specifications, documentation and primary repositories;
2. original papers and reproducible benchmark reports;
3. verified engineering implementations;
4. credible practitioner reports;
5. community/social discovery signals.

LinkedIn and community sources are valuable discovery channels but are not automatically authoritative.

## Research Workflow

~~~text
Discover
  ↓
Fetch
  ↓
Extract / Normalize
  ↓
Assess authority
  ↓
Verify important claims
  ↓
Rank evidence
  ↓
Store with provenance
  ↓
Retrieve for task
~~~

## Evidence Record

A material knowledge item should preserve, where available:

~~~text
source
source_type
claim
evidence
authority
confidence
verification_status
published_at
retrieved_at
freshness
applicability
~~~

Recommended verification states:

~~~text
VERIFIED
PARTIALLY_VERIFIED
UNVERIFIED
CONTRADICTED
INFERENCE
~~~

## Retrieval

The initial abstraction must support hybrid retrieval using some combination of:

- semantic similarity;
- lexical matching;
- metadata filters;
- source authority;
- recency/freshness;
- task applicability;
- optional reranking.

Do not lock the architecture to a particular vector database before real retrieval requirements are known.

## Freshness

Use live research when:

- the user asks for latest/current information;
- software/hardware behavior may have changed;
- model/framework versions matter;
- a benchmark or recommendation depends on recent evidence;
- repository status/release information matters.

Stable knowledge need not be re-researched unnecessarily.

## Recommendation Discipline

The agent must distinguish:

~~~text
Fact
Estimate
Hypothesis
Recommendation
Unknown
~~~

It must never turn a discovery signal into a verified fact without appropriate evidence.

It must not invent citations, benchmark numbers, release facts or source content.
