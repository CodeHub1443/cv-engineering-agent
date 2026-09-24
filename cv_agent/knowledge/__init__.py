"""
cv_agent.knowledge — the provenance-gated context/knowledge boundary (ADR-0006).

Owns the typed contract for a stored knowledge item (claim + provenance + source
class + freshness horizon), fail-closed provenance validation, deterministic
storage/retrieval, and bounded context assembly for the reasoning layer to read.

This package imports nothing from cv_agent.execution, cv_agent.skills,
cv_agent.graph, cv_agent.tools, or cv_agent.llm — enforced by
tests/test_knowledge.py's structural test. It does not acquire information (no web
fetching, no research execution — that is future work), does not reason about or
rank claims by relevance, and ships no durable persistence backend: only an
in-memory reference KnowledgeStore. See ADR-0006 for the full design and the
explicit list of what this package deliberately does not yet do.
"""
