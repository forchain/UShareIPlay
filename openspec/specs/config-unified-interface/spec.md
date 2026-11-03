# Spec: Give the config one interface

## Problem Statement

Configuration handling across UShareIPlay is fragmented across eight distinct call patterns and ad-hoc dictionary probes. Callers and subsystems must guess whether they are interacting with the root configuration mapping (`config.yaml`) or an application section (`soul` or `qq_music`):

1. **Root-vs-Section Ambiguity and Fragmented Probes**:
   Callers must know multiple shapes and defensively probe keys in different ways:
   - `config["elements"]` (`core/ui/element_finder.py:279`) assumes a section dictionary.
   - `config.get("soul", {}).get("elements")` (`managers/event_manager.py:263`) assumes a root dictionary.
   - `config.get("elements") or config.get("soul", {})...` (`managers/seat_manager/seat_observation.py:409`) tolerates both shapes with dual-shape fallback probes.
   - `config.get("soul", {}).get("elements")` in `core/element_wrapper.py:221` was passed a section mapping (`soul_handler.config`), causing `config.get("soul")` to always evaluate to `None`.
2. **Silently Broken Invariants and Dead Overrides**:
   Because `core/element_wrapper.py:221` probed `config.get("soul")` on a section mapping, the override for `message_reply_view` and `message_reply_content` declared in `config.yaml:92-93` never took effect in runtime. It silently fell back to hard-coded defaults, violating the AGENTS.md invariant that `config.yaml` is the single source of truth for element selectors without raising any error or warning.
3. **Restated XPath and Locator Rules**:
   The rule determining whether a selector string represents an XPath (`//` prefix) or an Android resource ID was restated across four distinct modules (`element_finder.py:277, :351`, `event_manager.py:371`, `gesture_handler.py:219`, `seat_panel_driver.py:421`). Divergence between relative (`.//*`) and absolute (`//*`) XPath construction led to fragile DOM queries.
4. **Fragile Reload and Dict-Identity Coupling**:
   Hot reload in `ConfigReloadManager` required maintaining raw dictionary identities through fragile in-place mutations across three distinct dict objects, guarding against reference decoupling rather than encapsulating reload behind a stable facade.
5. **Documentation Drift**:
   `docs/config.md` historically documented non-existent keys such as top-level `roles:`, `sleep.start_hour`, and top-level `memory:`, masking the true configuration structure (`soul.room_owner`, `sleep.start`, and `llm.memory`).

## Solution

Introduce a unified `ConfigView` facade and `Locator` value object seam (conforming to ADR-0009 and ADR-0012) providing a single, strongly-typed interface for all configuration access across root, application sections, and UI selectors:

1. **Locator Value Object**:
   A frozen value object encapsulating selector syntax and resolution rules in one place:
   - Evaluates whether a selector is an XPath or resource-id.
   - Produces Appium locator tuples `(AppiumBy.XPATH / AppiumBy.ID, value)`.
   - Generates absolute XPaths and relative-child XPaths (`.//*[@resource-id=...]` or `./...`).
   - Executes node matching tests against parsed XML/DOM elements, preserving existing prefix/suffix semantics.
2. **Config Section View (`ConfigSectionView`)**:
   A dedicated view for app sections (`soul`, `qq_music`):
   - Exposes `element(key) -> Locator` with fail-fast validation raising `MissingElementKey` on missing selectors.
   - Exposes `maybe_element(key) -> Optional[Locator]` for explicitly optional selector lookups.
   - Exposes `value(key, default)` and `require(key)` for scalar section parameters.
3. **Root Config View (`ConfigView`)**:
   A dedicated view for root configuration:
   - Exposes section accessors: `config.soul`, `config.music`, `config.section(name)`.
   - Exposes `command_entries` and root values without requiring raw dictionary manipulation.
4. **In-Place Live Delegation & Reload**:
   The view wraps the underlying configuration mapping without copying it. In-place reload modifies the wrapped mapping directly through the view, keeping object identities stable across reload cycles without requiring callers to re-wire dependencies.
5. **Fail-Fast Boot Validation**:
   Validate required element keys at startup in the composition root (`AppController`), loudly rejecting missing required selectors before UI automation begins.

## User Stories

1. As a bot developer configuring UI selectors, I want element overrides in `config.yaml` to reliably take effect at runtime without being swallowed by dead fallback branches.
2. As a room operator, I want the bot to fail immediately at startup with an informative error if a required element selector is missing from `config.yaml`, rather than failing during live room operation.
3. As a developer adding UI automation features, I want a single `section.element(key) -> Locator` method that provides Appium locators, relative XPaths, and node matchers consistently without restating XPath prefix logic.
4. As a test writer, I want to inject typed `ConfigView` / `ConfigSectionView` instances or mocks into handlers and managers with clear error reporting on missing keys.
5. As a developer updating configuration during runtime, I want hot reload to update view data in-place without breaking reference identity in long-lived manager singletons.
6. As a maintainer reviewing configuration documentation, I want `docs/config.md` to document only valid, active keys that match the runtime configuration schema.

## Implementation Decisions

- **New Core Module (`ushareiplay.core.config_view`)**:
  - `Locator`: Frozen dataclass encapsulating `kind`, `value`, `appium`, `absolute_xpath`, `relative_xpath`, and `matches(node)`.
  - `ConfigSectionView`: Section interface providing `.element(key)`, `.maybe_element(key)`, `.value(key, default=...)`, and `.require(key)`.
  - `ConfigView`: Root interface providing `.soul`, `.music`, `.section(name)`, `.command_entries`, `.reload(new_mapping)`, and `.data`.
  - Hierarchy of explicit exceptions: `ConfigError`, `MissingConfigSection`, `MissingConfigKey`, `MissingElementKey`.
- **Composition Root Integration (`ushareiplay.core.app_controller`)**:
  - `AppController` wraps loaded configuration mappings into `ConfigView`.
  - Injects `config.soul` and `config.music` into `SoulHandler` and `QQMusicHandler` respectively.
  - Verifies completeness of required UI element keys during startup initialization.
- **Strict No-Raw-Dict Contract (ADR-0012)**:
  - `ConfigView` and `ConfigSectionView` inherit from `object` (not `dict`), disallowing raw indexing `view[...]` or `.get(...)`.
  - Calling code across `managers/`, `commands/`, `core/`, and `state/` migrates from dictionary subscripting to typed view methods (`.value(...)`, `.element(...)`, `.section(...)`).
- **Elimination of Dead Fallback Code**:
  - Remove dead branch in `core/element_wrapper.py` probing `config.get("soul")`.
  - Remove hardcoded selector fallbacks for quoted replies, seat panels, and event detection.
- **Documentation Alignment**:
  - Update `docs/config.md` and `GLOSSARY.md` to define `Config View` and `Locator`, removing legacy references to non-existent config keys.
  - Document architectural decisions in `docs/adr/0012-config-view-and-locator-seam.md` and amend `docs/adr/0009`.

## Testing Decisions

- **Unit Testing Locator and View Semantics**:
  - Verify `Locator.from_value()` correctly identifies XPath vs ID strings.
  - Verify `appium`, `absolute_xpath`, `relative_xpath`, and `matches()` generate correct formats for both ID and XPath selectors.
  - Verify `ConfigSectionView.element()` returns `Locator` for valid keys and raises `MissingElementKey` with section and key name for missing keys.
  - Verify `ConfigSectionView.maybe_element()` returns `None` for absent keys without raising.
  - Verify `ConfigView.reload()` mutates underlying data in-place while preserving identity of `ConfigView` and child `ConfigSectionView` instances.
- **Fail-Fast Startup Verification**:
  - Test that missing required element keys in `config.yaml` raise fatal errors during startup validation.
  - Test that `config.local.yaml` attempts to override element maps are explicitly rejected.
- **Consumer Migration Tests**:
  - Verify element finder, event manager, seat observation, and quoted message extraction operate cleanly with `Locator` and view interfaces.
  - Verify root and soul section readers access configuration parameters via typed methods without raw dict operations.
- **Prior Art**:
  - `tests/test_config_view.py`
  - `tests/test_missing_element_keys_fail_loudly.py`
  - `tests/test_root_readers_view.py`
  - `tests/test_soul_section_readers.py`
  - `tests/test_config_reload.py`

## Out of Scope

- Changing the underlying YAML parser or switching from YAML to JSON/TOML.
- Redesigning `BaseCommand` parameter parsing or command execution signatures.
- Modifying Appium driver connection protocols or low-level Android touch gesture logic.
- Adding arbitrary schema validation engines (e.g. pydantic) beyond required element and section validation.

## Further Notes

- **Source Reference**: Candidate 01 of the 2026-11-02 architecture review ("Give the config one interface", ports & adapters).
- **ADR-0009 Alignment**: Fulfills the missing configuration layer of ADR-0009 §1 by providing strongly-typed constructor-injected configuration objects across all handlers and service singletons.
- **Single Source of Truth**: Enforces the AGENTS.md invariant that `config.yaml` is the sole source of truth for UI element selectors by eliminating silent fallback constants.
