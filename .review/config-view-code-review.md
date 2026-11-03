# Code Review — `feat/give-config-one-interface` (origin/main..HEAD)

- Diff: `f7342e3` — `feat(config): 给配置一个统一接口（ConfigView / Locator）`
- Size: 80 files, +2116 / −634 (**~2 750 changed lines** — well past the ~1 000-line reviewability bound)
- Scope: new module `core/config_view.py` (294 lines), an 80-file mechanical migration, 3 behaviour
  changes (fail-fast startup, `config.local.yaml` element rejection, dead-override resurrection),
  and docs (ADR-0012, `docs/config.md` rewritten, GLOSSARY entries).
- Verdict: **Request changes** on 5 items, then approve. The design is sound, the equivalence work is
  unusually careful, and the documented state is accurate — but the "fail loud" story it sells is only
  half-wired (R1–R3), `ConfigView.reload`'s identity contract is narrower than both the ADR and the
  GLOSSARY claim (R4), and `docs/config.md` asserts a "single read entry point" the code does not
  enforce (R5).

Reviewed with the five axes: correctness, readability/simplicity, architecture, security, performance.
No security surface is touched by this diff (no new input parsing, no new I/O beyond the existing
config file read). Performance is a non-issue at config scale except N4.

---

## R1 — Required: deleted fallbacks are not covered by the new fail-fast gate

The ADR's headline is "选择器要么来自 `config.yaml`，要么不存在" + "缺项在启动期当场失败". The diff
removes **14 hardcoded seat-panel selectors** and the reply-view defaults, but `REQUIRED_ELEMENTS`
(`core/config_view.py:59-69`) only guards 7 keys:

```
soul:      message_content, message_list, input_box, button_send,
           message_reply_view, message_reply_content
qq_music:  search_entry
```

Not guarded, yet no longer having a fallback:

- `managers/seat_manager/seat_panel_reader.py` — `seat_desk`, `left_seat`, `right_seat`,
  `left_state`, `right_state`, `left_label`, `right_label`, `left_default_name`,
  `right_default_name`, `left_avatar`, `right_avatar`, `left_rank`, `right_rank`, `empty_seat`
- `managers/seat_manager/seat_observation.py:1332` — `seat_desk`

Failure mode is silent by construction:

- `seat_panel_reader._element_locator` returns `None` and `find_child_element` logs at **debug**
  level (`seat_panel_reader.py:207-210`);
- `seat_observation._sync_viewport` returns `{}` (`seat_observation.py:1332`);
- `_avatar_image_count` returns `0`.

So a config that loses `seat_desk` **boots cleanly** and then silently observes no seats — exactly the
class of failure ADR-0012 exists to kill, reintroduced by the same commit.

Also missing: any test that validates the **shipped** `config.yaml`. `tests/test_missing_element_keys_fail_loudly.py`
builds its fixtures *from* `REQUIRED_ELEMENTS`, so it can never catch the file and the list drifting apart.

Remediation:

1. Extend `REQUIRED_ELEMENTS` with the seat-panel group (all 14 keys, or at minimum `seat_desk` +
   `left_*`/`right_*` state/seat/avatar), **or** move the required set into `config.yaml`
   (`soul.required_elements`) so the single-source rule covers "required" too and the list is not
   duplicated in Python.
2. Add one test: `ConfigView(ConfigLoader.load_config("config.yaml")).validate_required_elements()`.
   That is the test that would have caught a real 3 a.m. startup failure.
3. If a key is genuinely optional, say so at the call site (`.maybe_element` + a behaviour branch), not
   by silently returning `None` from a debug-level log.

## R2 — Required: the reload gate and the startup gate enforce different invariants

`ConfigReloadManager._validate` (`config_reload_manager.py:151-173`) checks that the `soul` / `qq_music`
sections exist and that their `elements` are dicts, but **never** runs `validate_required_elements()`.
Its own docstring says the point is to reject "接受了就等于把机器人推进一个重启也起不来的状态" — yet a
reload that drops `button_send` is accepted, and the *next* restart dies on exactly that selector.

The two gates must share one definition of "a config the bot can start from". One line fixes it:

```python
def _validate(self, config) -> Optional[str]:
    ...
    try:
        ConfigView(config).validate_required_elements()
    except ConfigError as exc:
        return f"配置文件缺少启动期必需的元素：{exc}"
    return None
```

(and extend the `tests/test_config_reload.py` parametrization with a "drop one required element" case).

## R3 — Required: `ConfigError` is thrown into a retry loop that swallows it

`ConfigError` / `MissingElementKey` / `LocalConfigOverrideRejected` have **zero** handlers anywhere in
`src/` (verified by grep). `__main__.main()` (`__main__.py:34-52`) catches bare `Exception`, prints
`App crashed (...), restarting...`, and loops 10 times **with no sleep**, then exits **0**.

Consequences of the new fail-fast behaviour:

- one missing selector ⇒ 10 identical crash lines, no hint that it is a config problem;
- exit status 0 ⇒ systemd/`docker restart` treat a fatal misconfiguration as a clean stop.

Remediation: treat `ConfigError` as fatal in `main()` — print section/key (the exception already carries
`.section` / `.key`), `sys.exit(2)`, do **not** retry. Optionally do the same for
`LocalConfigOverrideRejected`, whose message is already user-facing.

## R4 — Required: `ConfigView.reload` breaks its own identity contract in three ways

The ADR §3 and GLOSSARY promise: "根映射、视图实例、段视图实例的对象身份在重载前后都不变". Proven
otherwise (scratch script against the real module):

| case | observed |
|---|---|
| `view.reload(view.data)` (self-aliasing) | every cached section is **wiped**: `soul.data == {}` |
| new mapping omits `qq_music` | `root.data` loses the key, but `config.music` keeps serving the old `package_name` → view and data disagree |
| `nested = view.soul.maybe_section("elements")`, then reload | `nested.data` still `{'a': 'id/a'}`, live data `{'a': 'id/NEW'}` → silently stale |

Root causes:

1. `reload` does `view._data.clear(); view._data.update(new_section)` — when `new_section is view._data`
   (reload passed the live mapping, which the signature invites: `reload(new_mapping: Mapping[...])`),
   clear empties the source before the update reads it. **Total data loss**, no error.
2. Only depth-1 cached sections are refreshed; `ConfigSectionView.section()` / `maybe_section()` hand out
   uncached views wrapping whatever sub-dict was live at call time, so any consumer that keeps a nested
   view (the documented "长生命周期持有者不需要重新接线" case) freezes on the old config.
3. A section missing from the new mapping is never removed from `_sections`, so the stale view stays
   live while `data` no longer has the key.

Today no consumer caches a nested view (all call sites build one per call), so this is latent rather
than live — but it is precisely the invariant the ADR claims, and `ConfigReloadManager` will keep
calling `reload` for years. Fix:

- build `merged` from a snapshot first: `new_section = dict(new_mapping.get(name) or {})` then mutate —
  never mutate a source you are reading;
- either drop nested-view caching from the contract (say "depth-1 sections keep identity; nested views
  are snapshots") or track/replace child views;
- decide and test the removal semantics;
- add tests for these three cases; the current reload tests (`test_config_view.py:314-337`) cover only
  the happy path.

Also: `ConfigView.__init__` / `ConfigSectionView.__init__` / `reload` are annotated `Mapping[str, Any]`
but `reload` requires `.clear()`/`.update()`. `MappingProxyType` or a frozen mapping produces an
`AttributeError` **at reload time**, not at construction. Annotate `MutableMapping[str, Any]` (or accept
`dict` and copy on construction).

## R5 — Required (docs) / Consider (code): "唯一读入口" is not what the code does

`docs/config.md` states: "裸字典下标 `config["soul"]["elements"]` 与 `config.get(...)` 这类形状试探一律
不再使用". In practice **nine modules still accept both shapes**, via **five different ad-hoc coercion
rules**:

| location | coercion |
|---|---|
| `core/roles.py:132-151` `_split_config` | `ConfigView` / `ConfigSectionView` / raw dict (3 shapes) |
| `core/runtime_logging.py:22-35` `_logging_directory` | `ConfigView` / `Mapping` |
| `managers/keyword_manager.py:13-18` `_as_root_view` | `ConfigView` / dict→`ConfigView` |
| `core/command_catalogue.py:117-140` | `ConfigView` / dict / bare list |
| `managers/memory_manager.py:36-50` | `ConfigView` / dict |
| `managers/sleep_manager.py:71-81` | `ConfigView` / dict |
| `managers/room_state.py:126-140` | section view / root view (two view shapes) |
| `core/app_controller.py:52-56` | dict→`ConfigView` coercion at the composition root |

That is the same ambiguity the ADR set out to delete, now with a `ConfigView` costume — six modules still
take a raw mapping and six different rules decide what a "config" is. Two honest
options (do not leave the third, current state):

- **(a)** keep dual-shape acceptance only at the composition root, and route every other conversion
  through **one** named helper (`ConfigView.coerce(obj)`), deleting `_as_root_view`, `_split_config`'s
  view branch and `_logging_directory`'s duplicate branch; or
- **(b)** keep the per-module adapters but correct `docs/config.md` to say the view is the canonical
  entry point while a handful of legacy seams still accept raw mappings.

Also worth noting: `roles._split_config` does `dict(config.data)` on **every** `RolePolicy` construction
(`command_manager`, `info_manager`, `message_manager`, `playback_muting`, `level`), copying the whole
config map per message. Passing the view through to `_find_config_value` (it only reads keys) avoids
that copy — free simplification.

## R6 — Consider: `Locator.from_value` cannot express a relative XPath, and `relative_xpath` keeps a dead branch

`from_value` classifies only `//`-prefixed strings as XPath (`config_view.py:88-93`), so a `.//`-prefixed
selector becomes a **resource-id** whose value is the literal XPath. Yet:

- `relative_xpath` (`config_view.py:109-113`) still contains the `.`-prefixed branch — reachable only by
  direct `Locator(kind="xpath", ...)` construction. The new test says so out loud
  (`tests/test_config_view.py:165-170`: "这一条只能由直接构造的 xpath Locator 走到").
- The old seat reader **did** honour `.`-prefixed selectors
  (`origin/main:seat_panel_reader.py`: `if selector.startswith("//") or selector.startswith(".")`).
  So for that config form the new unified rule is a **silent behaviour change**, while ADR §"行为等价性"
  claims the derived XPath forms are "与各模块此前各自实现的口径逐条对齐".
- `_selector_present` (`event_manager.py:291-303`) keeps `locator.kind == "xpath"` for the branch and
  then feeds `selector` (not `locator.absolute_xpath`) into `root.xpath(...)` on the XPath branch —
  harmless today, but it means the Locator abstraction is bypassed right where it was introduced to help.

Pick one: make the classifier explicit and complete (`startswith(("//", "./", ".//"))`, or "contains
`/` or `[` ⇒ XPath"), or delete the dead branch and the ADR sentence that promises parity. No current
`config.yaml` value is affected (verified: no selector starts with `.`), so this is fixable cheaply now.

## R7 — Consider: leftover second config sources at runtime

- `managers/room_profile/manager.py:1191-1205` `_soul_config()` falls back to
  `ConfigLoader.load_config()` when `handler.config` is not a view. In production `handler.config` is
  always a `ConfigSectionView`, so this branch is dead — and if it ever runs it silently reads the file
  from disk instead of the live (possibly hot-reloaded) configuration. Return an empty view or raise;
  do not re-enter the loader from a manager.
- `managers/music_manager.py:82-95` returns `ConfigView({})` when the controller/handler config is not a
  `ConfigView`. That silently disables the old-song filter (all defaults) instead of reporting bad
  wiring. Same shape in `event_manager._root_config` (`ConfigView({})`) and
  `post_party_create_automation._cfg` (three `ConfigSectionView(..., {})` constructions).
- These empty-view constructions are repeated ~6 times. One `ConfigSectionView.empty(name)` /
  documented `EMPTY_ROOT` would at least make the "silently empty" behaviour greppable and reviewable.

`core/element_wrapper.py:215-240` is the clean version of this pattern: no config ⇒ `None`, and the
startup gate guarantees the elements exist. Keep that one, drop the rest.

## Nits (author may ignore)

- **N1** `config_view.py:267-275`: the `try/except MissingConfigSection: raise MissingConfigSection(...)`
  re-raises the identical exception from the same call — delete the try/except.
- **N2** `config_view.py:185-197` vs `229-249`: `ConfigSectionView.section()`/`maybe_section()` allocate a
  **new** view per call, while `ConfigView.section()` caches and documents "同一段名恒返回同一实例".
  Same method name, opposite identity contract, in a module whose whole selling point is identity. Cache
  nested views (and then R4's nested-staleness becomes mandatory to solve) or state the asymmetry.
- **N3** `config_view.py:115-133`: `matches()` swallows `Exception` and returns `False`; a typo'd XPath
  silently matches nothing. In a change whose thesis is "fail loudly", let the lxml error surface (or log
  it once).
- **N4** `Locator.matches` XPath branch re-evaluates the whole document per candidate node, and
  `element_wrapper._find_node_with_locator` calls it for every node in `node.iter()` ⇒ O(n²). Only bites
  if `message_reply_view` is configured as an XPath (today it is an id). Evaluate the XPath once per
  container and compare identity with `is` instead.
- **N5** `config_loader._reject_element_overrides` hardcodes `("", "soul.", "qq_music.")`; a third app
  section would silently escape the guard. Iterate the mapping recursively, or derive section names.
- **N6** `ConfigView.music` maps to `qq_music`, and `soul`/`music` are hardcoded app names inside the
  otherwise generic config layer. `.qq_music` (with `.music` kept as a documented alias) would read
  better next to `section("qq_music")`, which the same file already uses.
- **N7** `reload()`'s per-section `clear()`+`update()` is not atomic; a thread reading mid-reload can see
  an empty section. Pre-existing (the old `_apply_in_place` had the same hole), so not a regression —
  but a single `dict.__setitem__` swap per section would remove it for free.
- **N8** Repo has no ruff/mypy config, so the `Mapping`-vs-mutable and `kind: str` invariants above are
  unverifiable by machine. `Literal["xpath", "id"]` + a `__post_init__` check on `Locator.kind` would
  make the "two kinds only" claim real instead of prose; today `Locator(kind="bogus")` sends
  `absolute_xpath` down the id path and `matches` down the XPath path — the two consumers disagree about
  the same invalid state.

## Change-shape observations (process, not code)

- **One commit carries four changes**: new abstraction + 80-file mechanical migration + three behaviour
  changes (fail-fast, local-override rejection, dead-override resurrection) + docs. The behaviour changes
  are the only part a reviewer must reason about, and they are the hardest to find in the diff. Splitting
  them (refactor first, behaviour changes second) would have made R1–R3 obvious. Reviewers will ask for
  this next time; consider `git rebase -i` before opening the PR.
- **`config.local.yaml` element overrides now hard-fail at startup** (`LocalConfigOverrideRejected`).
  That is a deploy-breaking change for any machine that has such a file today. ADR-0012 acknowledges it;
  a one-line note in the PR body / release note ("delete `elements*` keys from your `config.local.yaml`
  or the bot will refuse to start") would save someone an outage. Error message itself is good.
- **File size**: `room_profile/manager.py` is still 1 990 lines. This diff touches it without making it
  smaller; R7's fix (drop the disk re-read) is the natural place to shed a responsibility.
- **Test mix**: the new `tests/test_config_view.py` has ~10 tests for trivial getters (`value`/`require`
  round-trips) and 3 shallow reload tests. The risky logic — alias safety, section removal, nested
  identity, invalid `kind` — has none. Flip that ratio.

## Verification performed

| check | result |
|---|---|
| `pytest -q` (venv, 2 631 tests) | **2 608 passed**; 1 failed + 22 errors, all in `test_install_script.py` / `test_init_worktree_script.py` / `test_run_sh_config_link.py` caused by the harness's broken `GIT_CONFIG_COUNT` env var — re-ran those 3 files with a clean env: **33 passed** |
| `compileall src/ushareiplay` | OK |
| removed hardcoded selectors vs `config.yaml` | all 16 (`gReplyView`, `tvReplyContent` + 14 seat keys) present with **identical values** — equivalence claim holds for the shipped config |
| `docs/config.md` documented paths vs `config.yaml` | 0 mismatches; counts verified: `soul.elements` 188, `qq_music.elements` 84, `commands` 38, top-level keys exactly the 10 documented |
| ADR claim "`config.get("soul")` on a section map was always `None`" | confirmed against `origin/main:element_wrapper.py` — genuine dead-branch bug, genuinely fixed |
| removed test assertions | all 17 replaced with view-equivalent assertions; no coverage silently dropped |
| no raw-dict access left in `src/` | true for subscript/`.get` on config (only `config_reload_manager` still calls `.get` on the new mapping), but 6 modules still accept a raw mapping (R5) |

What is **not** verified (and should be before merge): the three `reload` failure modes in R4 do not
currently have tests; nothing exercises the seat-panel path with a `config.yaml` that is missing
`seat_desk` (R1); nothing exercises a reload that drops a required selector (R2); and no runtime/E2E run
was performed in this review (the change is config-read-only, so unit-level equivalence is strong
evidence, but the fail-fast path changes start-up behaviour and deserves one manual `python -m
ushareiplay` boot with a deliberately broken selector — expect `MissingElementKey` naming the key).
