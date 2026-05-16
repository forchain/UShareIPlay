```markdown
# UShareIPlay Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill introduces the core development patterns and conventions used in the UShareIPlay Python codebase. It covers file organization, code style, commit practices, and testing patterns, providing a reference for consistent contributions and maintenance.

## Coding Conventions

### File Naming
- Use **snake_case** for all file names.
  - Example: `user_profile.py`, `game_manager.py`

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .models import User
    from .utils import calculate_score
    ```

### Export Style
- Use **named exports** (explicitly define what is exported).
  - Example:
    ```python
    __all__ = ["User", "GameManager"]
    ```

### Commit Messages
- Follow the **conventional commit** format.
  - Prefixes: `fix`, `feat`
  - Example:
    ```
    feat: add support for multiplayer game sessions
    fix: resolve crash when loading user profile
    ```

## Workflows

### Code Contribution
**Trigger:** When adding new features or fixing bugs  
**Command:** `/contribute`

1. Create a new branch for your changes.
2. Follow coding conventions for file naming and imports.
3. Write clear, conventional commit messages (use `fix:` or `feat:` prefixes).
4. Add or update tests as needed.
5. Submit a pull request for review.

### Testing
**Trigger:** When verifying code changes  
**Command:** `/test`

1. Identify test files (pattern: `*.test.*`).
2. Run tests using the project's preferred method (testing framework is unspecified; check project docs or use `python -m unittest` as a default).
3. Ensure all tests pass before merging changes.

## Testing Patterns

- Test files follow the `*.test.*` naming convention.
  - Example: `user_profile.test.py`
- Testing framework is **unknown**; check for test runners or use standard Python testing tools.
- Place test files alongside the code they test or in a dedicated `tests/` directory.

#### Example Test File
```python
# user_profile.test.py

from .user_profile import UserProfile

def test_user_creation():
    user = UserProfile("Alice")
    assert user.name == "Alice"
```

## Commands
| Command      | Purpose                                 |
|--------------|-----------------------------------------|
| /contribute  | Start the code contribution workflow    |
| /test        | Run all tests in the codebase           |
```
