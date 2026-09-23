# Dual-Layer User Memory Architecture with Decoupled Lifecycle Consolidation

## Status
Accepted

## Date
2026-09-07

## Context
Natural language interactions via `@我` require continuity: remembering user preferences (favorite singers, nicknames, specific rules) and room dynamics across sessions. However, sending entire raw chat histories to the LLM exceeds token limits, increases costs, and leaks unrelated conversations. Furthermore, running LLM memory distillation synchronously during live chat risks request timeouts and delays public room message processing.

## Decision
Implement a **Dual-Layer User Memory System** managed by `MemoryManager`:

1. **Short-Term Memory**:
   - Per-user raw interaction log stored in SQLite (`user_memories` / `@群主` chat lines).
   - Unconsolidated messages since the last update cursor (`last_consolidated_at`).
   - Injected into prompt context during active `@我` conversational turns.

2. **Long-Term Memory**:
   - Structured JSON document containing two distinct sections:
     - **Immutable Directives**: Hard user constraints, preferred honorifics, and explicit rules (persisted as unescaped UTF-8 JSON; immune to automated summarization drift unless explicitly edited by user).
     - **Evolving Profile**: Distilled conversational summaries, topics discussed, and musical tastes.

3. **Decoupled Lifecycle Consolidation**:
   - Consolidation runs in the background triggered exclusively by room lifecycle events (`room_created`, `room_closed`) and user presence events (`user_enter`, `user_exit`).
   - Gated by a minimum unsummarized message threshold to avoid wasteful LLM calls.
   - Execution timeout is fully decoupled from interactive chat resolution timeouts.

## Alternatives Considered
- **Synchronous summarization on each message**:
  - *Rejected*: Incurs 2-4 second latency overhead and exhausts LLM rate limits during lively room chatter.
- **Pure in-memory vector database**:
  - *Rejected*: Overkill for Soul App room scale (<100 active members); adds complex native dependencies, memory bloat, and complicates SQLite-only backup/portability.
- **Unstructured text notes**:
  - *Rejected*: Prone to hallucination and losing critical user boundary rules during LLM consolidation passes.

## Consequences
- Fast response times for interactive commands while retaining deep conversational context.
- Zero risk of chat blocking from background memory summarization.
- Stable user rules via immutable directive preservation across restarts.
