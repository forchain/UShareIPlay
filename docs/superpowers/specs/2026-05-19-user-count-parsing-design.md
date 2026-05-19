# Design Spec: User Count Parsing Fix

**Date:** 2026-05-19
**Status:** Approved
**Topic:** Handle change in online user count text format

## 1. Problem Description
The online user count text in the UI has changed from "x人" (e.g., "6人") to "x人在线" (e.g., "6人在线"). The current parsing logic in `UserCountEvent` fails to parse the new format because it tries to convert "6在线" to an integer after replacing "人" with an empty string.

## 2. Proposed Solution
Switch to a robust regex-based extraction of digits. This will handle both the old and new formats, as well as potential future variations.

### 2.1. Logic Update
- Use `re.search(r'(\d+)', user_count_text)` to find the first sequence of digits.
- Extract the matched group and convert it to `int`.

### 2.2. Implementation Details
- File: `src/ushareiplay/events/user_count.py`
- Method: `UserCountEvent.handle`

## 3. Testing Strategy
A new unit test will be created to verify the parsing logic.

### 3.1. Test Cases
- "6人" -> 6
- "6人在线" -> 6
- "123" -> 123
- "在线 10 人" -> 10
- Empty string -> Fail (return False)
- "无数据" -> Fail (log warning, return False)

### 3.2. Test File
- `tests/test_user_count_event.py`

## 4. Design Review
- **Architecture:** Simple logic update in an existing event handler.
- **Robustness:** High, regex handles various string formats.
- **Safety:** Logging preserved for troubleshooting.
