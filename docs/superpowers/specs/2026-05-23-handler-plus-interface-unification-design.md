# Design Spec: Handler Plus Interface Unification

**Date:** 2026-05-23
**Status:** Approved
**Topic:** Replace `plus` UI interface names with default names

## 1. Problem Description
`AppHandler` and `ElementFinder` currently expose two parallel UI APIs:

1. legacy basic methods (`wait_for_element`, `try_find_element`, etc.) that accept explicit locators
2. suffix-style methods that accept config element keys

Project usage has already converged on the suffix-style methods across handlers, managers, commands, and tests. Keeping both API families creates naming noise and maintenance overhead.

Goal: keep only the current key-based behavior, remove the old basic behavior, and keep one default API naming scheme.

## 2. Scope and Non-Goals

### In Scope
- Production code under `src/`
- Tests under `tests/`
- Documentation under `docs/`, including existing design/spec docs with old method names

### Out of Scope
- Behavioral changes to element lookup semantics, timeout strategy, or logging policy
- Appium interaction model changes

## 3. Proposed Design

### 3.1 API Surface After Cleanup
Keep one method family only (default names):

- `wait_for_element(element_key, timeout=10)`
- `wait_for_element_clickable(element_key, timeout=10)`
- `try_find_element(element_key, log=False, clickable=False)`
- `find_elements(element_key)`
- `find_child_element(parent, element_key)`
- `find_child_elements(parent, element_key)`
- `wait_for_any_element(element_keys, timeout=10)`
- `try_find_any_element(element_keys)`

These methods will implement the current `plus` behavior (element-key driven lookup via config).

### 3.2 Module-Level Changes
- `src/ushareiplay/core/ui/element_finder.py`
  - remove legacy locator-argument implementations
  - rename suffix-style methods to default names
  - update internal cross-calls (`try_find_element` -> `wait_for_element_clickable`, etc.)

- `src/ushareiplay/core/app_handler.py`
  - remove dual API forwarding
  - keep only forwarding methods with default names mapped to unified `ElementFinder` methods

### 3.3 Call-Site Migration
Replace all call sites from the old suffix-style names to unified default names in:
- handlers
- managers
- commands
- events
- wrappers and helper utilities
- tests and test doubles/stubs
- docs and spec documents

No compatibility aliases are kept.

## 4. Data and Control Flow Impact
Runtime data flow does not change:

1. caller passes element key
2. `AppHandler` forwards to `ElementFinder`
3. `ElementFinder` resolves key to locator via config
4. Appium locator call executes

Only public method names change.

## 5. Risks and Mitigations

### Risk 1: Missed references cause runtime failures
- Mitigation: global search for removed method names and removed old signatures after migration

### Risk 2: test stubs still define old names
- Mitigation: migrate all stubbed handler interfaces in tests to new default names

### Risk 3: stale docs keep obsolete API names
- Mitigation: include `docs/` and `docs/superpowers/specs/` in rename sweep

## 6. Verification Plan

1. Static checks
- search for residual removed method names

2. Focused tests
- run key suites that stub handler interfaces and exercise room/music flows

3. Full test run
- run `uv run pytest -q`

Success criteria:
- no runtime references to removed names
- tests pass with unified interface naming
- docs/specs no longer mention old `plus` method names
