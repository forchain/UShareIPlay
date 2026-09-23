# Configurable Role Hierarchy and Operator Protection Policy

## Status
Accepted

## Date
2026-09-10

## Context
UShareIPlay operates in public Soul App rooms where account risk controls and rate limits are severe. Different actors interact with the bot:
1. Public room visitors (unknown or low-level users).
2. Trusted room members and VIPs.
3. In-app room administrators.
4. Backend operators (human console operators, repository/bot owners).
5. Internal automated actors (`Timer`, `Console`, `Agent`).

Previously, user level checks were simple integer comparisons (0-9) queried from the database. This caused issues:
- System automated roles were confused with public users.
- Backend room owners could not override permissions if their in-game nickname changed or differed from the host account.
- Automated commands during late-night hours disrupted sleeping room members, but night guards also blocked human operators trying to administer the room.

## Decision
Introduce a unified `RolePolicy` boundary with distinct user tiers and behavioral protections:

1. **Role Categorization**:
   - **Human Operators**: Bot owner (`soul.room_owner`), Console operator (`Console`), and in-app room administrators.
   - **System Users**: Automated internal actors (`Timer`, `Agent`, `System`). Always bypass standard level checks.
   - **Privileged Users**: Union of Human Operators, System Users, and users with level ≥ 9.
   - **Normal Users**: Standard room visitors subject to database level checks (levels 0-8).

2. **Late-Night Sleep Guardian Protection**:
   - Automated commands from normal users or background timers are blocked during sleep hours (default 23:00 to 06:00).
   - Human operators (Owner, Console, Admin) and explicit natural language interactions marked `sleep_exempt` (e.g. direct `@我` mentions) are permitted to break through sleep locks.

3. **Backend Room Owner Identity**:
   - Configurable `soul.room_owner` defines the authoritative backend owner identity regardless of in-app nickname or temporary room host transfers.

## Alternatives Considered
- **Hardcoding admin names in Python code**:
  - *Rejected*: Inflexible and risks committing sensitive account usernames to public version control.
- **Applying SleepGuardian universally to all actors**:
  - *Rejected*: Prevents human operators from emergency maintenance or manually queuing songs at night.

## Consequences
- Clean separation between automated automation roles, human operators, and public room members.
- Protects accounts from risk-triggering command floods during off-hours while preserving operational control.
- Configuration resides in `config.yaml` / `config.local.yaml` under `roles` and `soul.room_owner`.
