# Natural Language Command Resolution via LLM Translation

Natural language requests from users (especially newcomers) need to trigger actions without requiring them to memorize strict `:` command prefixes and syntax. Rather than implementing autonomous direct tool calling or streaming all public room messages to an LLM, we decided to implement **Natural Language Command Resolution** as an intent translation boundary behind `@我` mentions when keyword matching misses.

The LLM translates natural language utterances into standard UShareIPlay command strings (`:play`, `:vol`, etc.) or conversational text replies, which are pushed directly into `MessageQueue`.

This decision preserves our single-source-of-truth command pipeline (**Command Execution**), which owns user permission level checks, cooldowns, UI automation, and error retries. The prompt receives the speaker's permission level, command definitions, and current playback info to make informed semantic decisions and provide guided feedback when permissions are insufficient. When the LLM service is disabled, times out (3-5s), or encounters errors, the pipeline gracefully falls back to executing the existing `default_keyword`.
