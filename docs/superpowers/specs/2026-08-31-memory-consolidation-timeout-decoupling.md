# Design Spec: Decouple Memory Consolidation Timeout from Chat Resolution Timeout

**Date:** 2026-08-31  
**Status:** Ready for Implementation  

## Problem Statement

When UShareIPlay performs background Memory Consolidation for active users, the long-term memory distillation process frequently fails with `Error calling consolidation LLM: The read operation timed out`. Because consolidation tasks send long prompts (including existing immutable directives, user profile summary, and at least 10 user chat messages) and require structured JSON generation, remote LLMs (such as DeepSeek, OpenAI, MiniMax) take several seconds to respond. However, memory consolidation currently reuses the short socket timeout configured for real-time natural language command resolution (defaulting to 4.0s). When this short timeout expires, the background consolidation call aborts, leaving user chat logs unconsolidated and the consolidation cursor unadvanced.

## Solution

Decouple the HTTP timeout of background Memory Consolidation from the real-time Natural Language Command Resolution timeout. Provide dedicated, configurable timeout support for memory consolidation operations (with a sensible default of 30.0s, configurable via `llm.memory.timeout`), and enable the underlying LLM HTTP transport layer to accept per-call custom timeouts. This ensures background memory consolidation can reliably complete multi-message distillation without disrupting or inflating the strict low-latency timeouts required for instant in-room chat command resolution.

## User Stories

1. As a party room bot operator, I want background memory consolidation to have a dedicated, sufficiently generous LLM request timeout (default 30 seconds), so that complex user history distillation and JSON generation succeed even when the remote LLM takes longer than a few seconds.
2. As a party room bot operator, I want real-time chat command resolution to maintain its tight latency timeout (default 4.0 seconds), so that live room chat interaction remains responsive and does not hang on unresponsive LLMs.
3. As a party room bot operator, I want to configure the memory consolidation timeout via configuration (`llm.memory.timeout`), so that I can adjust the timeout based on the latency characteristics of my chosen LLM provider.
4. As a party room participant, I want my multi-message conversation history to be reliably summarized and recorded into long-term memory, so that the bot remembers my preferences and directives across room sessions.
5. As a party room bot operator, I want memory consolidation failures due to network or timeout issues to continue protecting uncommitted data without corrupting existing directives or advancing cursors prematurely.
6. As a party room bot operator, I want clear and distinct error logging when a consolidation timeout occurs, indicating the configured consolidation timeout value for operational diagnosability.
7. As a developer, I want the transport layer to accept an optional timeout override per request, so that future subsystems needing distinct LLM timeouts do not need to duplicate HTTP client logic.
8. As a party room bot operator, I want existing installations without `llm.memory.timeout` in their configuration to automatically default to a safe 30.0s consolidation timeout without requiring manual configuration file edits.

## Implementation Decisions

- **Transport Layer Parameterization (Highest Seam)**:
  Extend the natural language resolver's HTTP call interface (`_call_api` / `_sync_http_call`) to accept an optional per-request timeout parameter (e.g. `timeout: Optional[float] = None`). When provided, the HTTP transport enforces that custom timeout; otherwise, it falls back to the instance's default chat resolution timeout (`self.timeout`).
- **Memory Manager Configuration & Timeout Injection**:
  Update `MemoryManager.configure()` to parse `timeout` from the `llm.memory` configuration section (defaulting to 30.0 seconds). Store this as an instance attribute (`self._timeout = float(mem_cfg.get("timeout", 30.0))`).
- **Consolidation LLM Invocation**:
  Update `MemoryManager._call_consolidation_llm()` to pass `timeout=self._timeout` when invoking the resolver's `_call_api()` interface.
- **Resilience and State Safety**:
  Maintain existing error handling semantics: if an exception (timeout or HTTP error) occurs during consolidation, log the error clearly, keep the cursor (`last_consolidated_at`) untouched, and return unchanged directives and profile.
- **Configuration Defaults & Examples**:
  Add `llm.memory.timeout` documentation to `config.yaml` and `config.local.yaml.example` with standard defaults (30.0s).

## Testing Decisions

- **Good Test Criteria**:
  Tests must assert external observable behavior without coupling to external network endpoints.
  - Verify that `NaturalLanguageResolver._call_api` and `_sync_http_call` pass custom timeouts to the underlying HTTP request mechanism.
  - Verify that `MemoryManager.configure` parses `timeout` with a default of 30.0 seconds.
  - Verify that `MemoryManager._call_consolidation_llm` passes the configured timeout down to the resolver.
  - Verify that when an LLM call succeeds within the consolidation timeout, memory updates and cursor advancement proceed normally.
- **Modules Tested**:
  - `ushareiplay.core.natural_language_resolver`
  - `ushareiplay.managers.memory_manager`
- **Prior Art**:
  - `tests/test_natural_language_resolver.py`
  - `tests/test_memory_consolidation_pipeline.py`

## Out of Scope

- Modifying the prompt template or JSON schema used for memory consolidation.
- Changing the retry frequency or debouncing logic of background worker loops.
- Altering the conversational command resolution timeout for real-time `@我` chat intake.

## Further Notes

None.
