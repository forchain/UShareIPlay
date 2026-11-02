# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Project Overview

UShareIPlay is a Python-based Android automation framework that controls **Soul App** (Chinese social platform) and **QQ Music** via Appium. It provides music playback management, room administration, and interactive features through a command-driven architecture. See `README.md` for the full command reference.

## Logging Policy (铁律)

**全局铁律**：严禁在循环监控、轮询、周期性检测（如座位观测、UI 锁获取/释放、心跳巡检等）中输出无行为触发的监控日志。
- **只有触发了具体行为才输出日志**：例如检测到座位/用户变更、解析并执行命令、进入/离开房间、发起弹窗交互或出现异常/错误时，才允许输出日志。
- **禁止在日常轮询中刷屏**：常规空转巡检、定时扫描、锁的常规获取与释放等内部机制，严禁使用 INFO/CRITICAL 等级别打印无动作的监控日志（仅可在排查问题时置于 DEBUG 级别），保持控制台与运行时日志整洁。

## OpenSpec Workflow

This repo uses OpenSpec for structured change management:

```bash
# Propose a new change
/openspec-propose

# Explore/investigate before implementing
/openspec-explore

# Implement tasks from a change
/openspec-apply-change

# Archive after completion
/openspec-archive-change
```

Change specs live in `docs/superpowers/specs/`. Active changes are tracked there with tasks, design docs, and implementation notes.

## GitHub Account Switching

### Account Switching
When creating or editing pull requests with `gh`, the correct GitHub account depends on the repository remote URL.
- **Rule**: Read `remote.origin.url` and extract the username before `@github.com` (e.g. `https://forchain@github.com/forchain/UShareIPlay` → `forchain`). Temporarily switch `gh` to that account for PR operations, then switch back.

Example:
```bash
git config --get remote.origin.url
gh auth status -h github.com
gh auth switch -h github.com -u <remote-username>

# PR operations (create/edit/view)
gh pr create ...

# Switch back
gh auth switch -h github.com -u <previous-active-username>
```

### Branch Naming (铁律)

分支一律用 `<type>/<slug>` 格式：类型前缀与 slug 之间**必须用斜杠分隔**。严禁使用
`forchain/fix-<slug>` 这类「属主前缀 + 连字符」的形式。

```bash
# ✅ 正确
fix/seat-panel-collapse-race
feat/invite-empty-seat
chore/ci-pytest-gate

# ❌ 错误
forchain/fix-seat-panel-collapse-race
forchain/feat-invite-empty-seat
```

- 类型前缀：`fix/`、`feat/`、`chore/`、`refactor/`、`docs/`、`test/`
- slug 用短横线小写，**不重复类型前缀**（`fix/seat-panel-collapse-race`，而不是
  `fix/fix-seat-panel-collapse-race`）
- 仓库里已存在的 `forchain/*` 历史分支不用回改，新建分支一律按本规则命名

## Agent Skills

### Issue tracker
GitHub Issues on `forchain/UShareIPlay`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels
Five canonical roles use default label names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs
Single-context layout: `GLOSSARY.md` at repo root and `docs/adr/` for ADRs. See `docs/agents/domain.md`.
