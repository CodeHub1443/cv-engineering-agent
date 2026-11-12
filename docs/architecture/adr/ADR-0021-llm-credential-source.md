# ADR-0021: LLM credential source

- **Status:** Accepted (accepted by owner, 2026-11-12; D-088)
- **Date:** 2026-11-12
- **Layer:** reasoning (LLM Gateway), plus the CLI entry point as composition root
- **Canon:** `[P§20]`, `[P§24]`, `[P§34]`
- **Supersedes / Superseded by:** supersedes D-033(5) and the credential paragraph of [ADR-0002](ADR-0002-llm-gateway.md) §3. Referenced by [ADR-0020](ADR-0020-llm-gateway-v2.md).
- **Issue:** #83

## 1. Context

- The Anthropic adapter reads `ANTHROPIC_API_KEY` from `os.environ` (`cv_agent/llm/anthropic_provider.py:27,78`).
  That name is shared with every Anthropic tool on the machine, so a key meant for another tool would silently be billed to this agent.
- The owner wants a project-scoped variable and a git-ignored project `.env` file whose values are not exported into the process environment.
- The committed `.gitignore` has no `.env` rule (it is ignored only through the local, unshared `.git/info/exclude`), and no committed Claude Code settings deny reading `.env`.

## 2. Responsibility `[P§34]`

- **This owns:** finding the gateway's API credentials, from the process environment and then the project `.env`, without ever exporting, logging or printing them.
- **This does NOT own:**
  - which provider is used — the router in [ADR-0020](ADR-0020-llm-gateway-v2.md);
  - CLI argument parsing — `cv_agent/__main__.py`;
  - secret storage at rest — the owner's git-ignored file;
  - OS ACLs on Windows — an accepted gap (§3.7).
- **Why this does not belong to an existing component:** `AgentConfig` must never hold secrets (ADR-0002 §4, `docs/APPROVALS.md`). The adapter alone cannot know the project root. The CLI must not contain provider names (`CLAUDE.md` §3.8). So the gateway owns the lookup and the CLI only triggers the file load.

## 3. Decision

1. Variable `CV_AGENT_ANTHROPIC_API_KEY`. `ANTHROPIC_API_KEY` is never read; there is no fallback.
2. Lookup order: the process environment, then values loaded from `<main checkout root>/.env`. The root is `repository_state_root().parent` (`cv_agent/experiments/provenance.py`), resolved by the CLI. If the root cannot be resolved, only the process environment is searched, and the error says so.
3. `.env` is parsed by a small own parser in `cv_agent/llm/credentials.py`, without python-dotenv:
   - `KEY=VALUE` lines, `#` comments, an optional `export ` prefix, and matching single or double quotes stripped;
   - no interpolation, no multiline values;
   - only keys matching `^CV_AGENT_[A-Z0-9_]+$` are kept;
   - a malformed line raises `LLMCredentialError` with the file path and line number, never the line text.
4. Loaded values live in a module-private mapping. **`os.environ` is never written.**
5. Only `cv_agent/__main__.py:main()` calls `load_project_env_file()`, once, before dispatch. Library users and tests get process-environment lookup only, unless they call it explicitly.
6. Adapters call `get_credential(name)`.
7. POSIX: the file must be owned by the current user with no group or other permission bits (`mode & 0o077 == 0`), otherwise it is refused with a `chmod 600` hint. Windows: the ACL check is skipped (accepted gap, documented).
8. A missing-key error names the variable and the searched locations (the environment, and the `.env` path or "not searched: <reason>"). It never contains a value. When `ANTHROPIC_API_KEY` is set, the error adds: "ANTHROPIC_API_KEY is set but ignored by design (ADR-0021)."
9. `.gitignore` gains `.env` and `.env.*` (slice C1).
10. A committed `.claude/settings.json` denies `Read(./.env)` and `Read(./.env.*)`. `.claude/settings.local.json` is never touched (slice C1).
11. A one-line rule is added to `CLAUDE.md` §3 and mirrored in `AGENTS.md`, folded into an existing rule line with no net growth (owner answer Q-R): never open, print or commit `.env`/`.env.*`; credentials come only from `get_credential()` (slice C1).
12. **Only the owner's Windows PC holds the key** (owner answer Q-G, 2026-11-12). The project `.env` with `CV_AGENT_ANTHROPIC_API_KEY` exists on that machine only, never copied to another machine, a CI runner or the Linux host. On any other machine a hosted call fails closed with `LLMCredentialError` (the missing-key error of item 8). This is what makes the daily budget in [ADR-0020](ADR-0020-llm-gateway-v2.md) a true whole-agent ceiling.

## 4. Alternatives considered

| Alternative | For | Against | Verdict |
|---|---|---|---|
| Keep `ANTHROPIC_API_KEY` | No change; SDK convention | Shared across tools, so the wrong key gets billed; this agent's spend cannot be told apart | Rejected |
| Fall back to `ANTHROPIC_API_KEY` | Convenience | A silent fallback is the ambiguity being removed | Rejected (owner) |
| python-dotenv | Mature | New dependency; its default `load_dotenv` writes `os.environ` | Rejected |
| Write `.env` values into `os.environ` | Simple | Leaks to every child process (skill and job subprocesses) | Rejected |
| OS keychain (`keyring`) | Better at rest | New dependency; differs per OS | Not now; revisit trigger |

## 5. Interface

Stubs only, marked PROPOSED until slice C2.

```python
# PROPOSED — cv_agent/llm/credentials.py
def load_project_env_file(path: Path) -> None: ...   # CLI main() only; never writes os.environ
def get_credential(name: str) -> str: ...            # name matches ^CV_AGENT_[A-Z0-9_]+$; raises LLMCredentialError
def searched_locations() -> tuple[str, ...]: ...     # for error messages; never values
def _reset_for_tests() -> None: ...
```

`LLMCredentialError` is defined in `cv_agent/llm/errors.py` ([ADR-0020](ADR-0020-llm-gateway-v2.md) §5).

## 6. Consequences

- **Enables:** a project-scoped key; a clear missing-key diagnosis; no secret in child processes.
- **Makes harder:** users of the SDK convention must set a new variable.
- **Costs (build, runtime, GPU, $):** about 120 lines plus tests; no dependency; no GPU; no spend.
- **Migration / blast radius if reversed:** `credentials.py` and one CLI line.

## 7. Acceptance test

- `tests/test_llm_credentials.py`: with no key anywhere, a hosted tier raises `LLMCredentialError` (the case on every machine except the Windows PC); environment beats `.env`; `.env` used when the variable is absent; `ANTHROPIC_API_KEY` alone yields an error containing "ignored by design" and never the value; the missing-key error names the variable and path and contains no value (sentinel check on `str` and `repr`); parser cases (comments, blanks, `export`, quotes, non-`CV_AGENT_*` keys ignored, malformed line number without the value); `os.environ` is unchanged after loading; POSIX mode 0644 refused and 0600 accepted (skipped on Windows).
- `tests/test_llm_structure.py`: no write to `os.environ` anywhere in `cv_agent/llm/`; `ANTHROPIC_API_KEY` appears in `cv_agent/` only in `credentials.py`.
- `tests/test_repo_hygiene.py`: `git check-ignore -q .env .env.local` succeeds (skipped outside a git checkout); `.claude/settings.json` contains both deny rules.

## 8. Revisit trigger

- A second hosted provider needs a key.
- The owner wants keychain storage.
- A Windows ACL check becomes required.
- The agent runs as a service rather than from the CLI.
