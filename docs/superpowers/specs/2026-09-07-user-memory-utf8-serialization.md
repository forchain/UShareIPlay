# Design Spec: Persist Immutable Directives as Unescaped UTF-8 JSON

**Date:** 2026-09-07  
**Status:** Ready for Implementation  
**Issue:** [#284](https://github.com/forchain/UShareIPlay/issues/284)

## Problem Statement

When bot operators and developers inspect or edit the database directly via database management tools or CLI (e.g. `sqlite3`, DBeaver, Navicat), the `immutable_directives` column in the `user_memories` table is stored using escaped Unicode escape sequences (e.g. `["\u79f0\u8c13: \u6d69\u54e5", "\u786c\u6027\u504f\u597d: \u559c\u597d\u5468\u6770\u4f26"]`). In contrast, `profile_summary` in the same table is stored as readable UTF-8 text. Reading and manually editing ASCII-escaped Unicode in `immutable_directives` during operational troubleshooting or direct database administration is error-prone, counterintuitive, and inconvenient.

## Solution

Configure `UserMemory.immutable_directives` (`fields.JSONField`) to use an explicit JSON encoder with `ensure_ascii=False` (e.g., `functools.partial(json.dumps, ensure_ascii=False, separators=(',', ':'))`). This ensures that Chinese characters and other non-ASCII content are persisted into SQLite as native UTF-8 JSON text, while maintaining full backward-compatibility with existing records and seamless Python-level deserialization in `UserMemoryDAO` and `MemoryManager`.

## User Stories

1. As a bot administrator inspecting the `user_memories` database table directly via CLI or GUI tools, I want the `immutable_directives` column to store readable UTF-8 Chinese characters, so that I can directly read, audit, and understand users' immutable directives without manual Unicode decoding.
2. As a bot administrator updating or repairing memory records directly in the database, I want to edit `immutable_directives` using plain Chinese text, so that manual data maintenance is straightforward and not prone to Unicode escaping syntax errors.
3. As a room participant interacting with the bot, I want my memory directives to be saved and loaded with complete fidelity and no semantic changes, so that the bot continues to recognize my honorifics and preferences seamlessly.
4. As a developer, I want `UserMemoryDAO` and `MemoryManager` to continue receiving native Python `list[str]` objects without requiring changes to business logic or prompt construction.
5. As a developer, I want existing user memory records previously saved with `\uXXXX` Unicode escaping to load and deserialize transparently without requiring data migration scripts or breaking reads.
6. As a bot administrator, I want the serialization format to remain standard, compliant JSON with compact separators (`(',' , ':')`), so that JSON parsers in SQLite or external reporting pipelines can process the column without syntax errors.

## Implementation Decisions

- **Custom JSON Encoder for `JSONField` (Single Seam)**:
  Define a UTF-8 JSON encoder using `functools.partial(json.dumps, ensure_ascii=False, separators=(',', ':'))` in `ushareiplay.models.user_memory` and pass it as the `encoder` argument to `fields.JSONField(default=list, encoder=_json_dumps_utf8)`.
- **Zero Business Logic Modification**:
  Keep `UserMemoryDAO` and `MemoryManager` unchanged. Because Tortoise ORM uses `json.loads` for deserialization (`decoder`), both UTF-8 literal characters and legacy `\uXXXX` sequences deserialize into identical Python `list[str]`.
- **Backward Compatibility**:
  Existing records containing `\uXXXX` remain fully valid and decodable. When an existing record is updated by `UserMemoryDAO.update_memory()`, it will naturally be re-serialized into readable UTF-8 text upon `.save()`.

## Testing Decisions

- **Good Test Criteria**:
  Tests must verify the external persistence behavior against the real SQLite storage engine and verify that both writing new UTF-8 records and reading legacy `\uXXXX` records produce identical Python data structures.
- **Modules Tested**:
  - `ushareiplay.models.user_memory`
  - `ushareiplay.dal.user_memory_dao`
- **Prior Art**:
  - `tests/test_user_memory_data_layer.py`

## Out of Scope

- Changing the underlying database column type (remains `JSON` / `TEXT`).
- Modifying other models that use plain text fields.
- One-off database migration scripts (existing records will be upgraded seamlessly on update or continue to read fine).

## Further Notes

None.
