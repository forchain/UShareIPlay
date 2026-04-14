## 1. Data Model And Persistence

- [ ] 1.1 Add a nullable self-referential canonical user field to the `User` model.
- [ ] 1.2 Add or update the database migration/init path so the `users` table persists the canonical user column.
- [ ] 1.3 Verify the canonical field can store `NULL` for original users and a referenced user ID for alias users.

## 2. Canonical User Resolution

- [ ] 2.1 Update `UserDAO.get_or_create(username)` to return the canonical user when the resolved user has a canonical mapping.
- [ ] 2.2 Ensure canonical resolution avoids self-reference and resolves alias targets to the final canonical user.
- [ ] 2.3 Review direct username-based user lookups in affected paths and align them with the canonical resolution approach where needed.

## 3. Admin Alias Command

- [ ] 3.1 Add a new administrator-only command for binding an alias username to a canonical username.
- [ ] 3.2 Implement command validation for missing parameters, self-reference, and invalid canonical targets.
- [ ] 3.3 Wire the new command into command loading and `config.yaml` so it is available in runtime.

## 4. Affected Business Flows

- [ ] 4.1 Verify enter, exit, and return event creation and execution use canonical user identity via the shared user resolution path.
- [ ] 4.2 Verify keyword ownership, lookup, execution, and deletion use canonical user identity via the shared user resolution path.
- [ ] 4.3 Verify seat reservation creation, lookup, and removal use canonical user identity via the shared user resolution path.
- [ ] 4.4 Verify permission level checks use the canonical user's level for alias usernames.

## 5. Validation

- [ ] 5.1 Add or update focused tests for canonical resolution and alias command behavior where practical in this repository.
- [ ] 5.2 Run targeted verification covering canonical event lookup, canonical keyword behavior, canonical seat reservation behavior, and command permission checks.
- [ ] 5.3 Document any known limitations, especially that pre-existing alias-owned data is not merged into the canonical user.
