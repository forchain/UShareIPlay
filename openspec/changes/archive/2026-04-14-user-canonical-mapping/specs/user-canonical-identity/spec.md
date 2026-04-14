## ADDED Requirements

### Requirement: Alias usernames SHALL resolve to the canonical user
The system SHALL allow a user record to reference another user record as its canonical identity. When a username maps to an alias user that has a canonical reference, all business logic that resolves that username through the standard user resolution path MUST use the canonical user as the effective identity.

#### Scenario: Alias username resolves to canonical user
- **WHEN** the system resolves a username whose user record has a non-null canonical reference
- **THEN** it MUST return the referenced canonical user as the effective user

#### Scenario: Canonical user resolves to itself
- **WHEN** the system resolves a username whose user record has no canonical reference
- **THEN** it MUST return that user record as the effective user

### Requirement: Canonical resolution SHALL preserve existing ID-bound behavior
The system SHALL preserve all configurations and permissions that are already bound to the canonical user's `users.id`, including event bindings, keyword ownership, seat reservations, and user level checks. Alias usernames MUST be treated as if they were the canonical user when those systems resolve the acting user.

#### Scenario: Alias triggers canonical event configuration
- **WHEN** a username mapped to an alias user triggers enter, exit, or return event handling
- **THEN** the system MUST evaluate and use the canonical user's existing event configuration

#### Scenario: Alias uses canonical keyword ownership and access
- **WHEN** a username mapped to an alias user adds, deletes, finds, or executes a user-owned keyword through the standard user resolution path
- **THEN** the system MUST use the canonical user's identity for ownership and access checks

#### Scenario: Alias uses canonical seat reservation identity
- **WHEN** a username mapped to an alias user creates, removes, or looks up a seat reservation through the standard user resolution path
- **THEN** the system MUST use the canonical user's identity for the reservation operation

#### Scenario: Alias inherits canonical permission level
- **WHEN** command permission checking resolves a username mapped to an alias user
- **THEN** the system MUST use the canonical user's level for permission evaluation

### Requirement: Administrators SHALL be able to bind an alias username to a canonical username
The system SHALL provide an administrator-only command that binds one username as an alias of another username. After the binding is saved, future standard user resolution for the alias username MUST resolve to the canonical user.

#### Scenario: Admin binds alias to canonical user
- **WHEN** an administrator binds alias username `A` to canonical username `B`
- **THEN** the system MUST persist a canonical reference from `A` to `B`
- **THEN** future standard user resolution for `A` MUST return `B` as the effective user

#### Scenario: Binding targets an alias username
- **WHEN** an administrator binds alias username `A` to username `B` and `B` already resolves to canonical user `C`
- **THEN** the system MUST persist `A` as an alias of `C`

#### Scenario: Binding rejects self-reference
- **WHEN** an administrator attempts to bind a username as an alias of itself
- **THEN** the system MUST reject the command and MUST NOT change stored mappings
