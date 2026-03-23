## ADDED Requirements

### Requirement: Local config file overrides main config
ConfigLoader SHALL detect `config.local.yaml` in the same directory as `config.yaml` and, if present, deep-merge its contents onto the main config. The result MUST reflect local values where specified, and main config values where not overridden.

#### Scenario: Local file present with partial overrides
- **WHEN** `config.local.yaml` exists and contains a subset of keys (e.g., `device.name`)
- **THEN** the loaded config SHALL use the local value for `device.name` and all other values from `config.yaml`

#### Scenario: Local file absent
- **WHEN** `config.local.yaml` does not exist
- **THEN** the loaded config SHALL be identical to `config.yaml` alone, with no error raised

#### Scenario: Local file is empty
- **WHEN** `config.local.yaml` exists but is empty
- **THEN** the loaded config SHALL be identical to `config.yaml` alone, with no error raised

### Requirement: Deep merge semantics for nested dicts
For nested dict structures, ConfigLoader SHALL merge recursively so that only the specified sub-keys are overridden without discarding sibling keys.

#### Scenario: Nested key override preserves siblings
- **WHEN** `config.local.yaml` specifies `device:\n  name: "new-device"` and `config.yaml` contains additional `device` sub-keys
- **THEN** all `device` sub-keys from `config.yaml` SHALL be preserved except `name`, which SHALL equal `"new-device"`

### Requirement: List values replaced wholesale
When a local config key maps to a list, ConfigLoader SHALL replace the entire list from `config.yaml` with the local list (no element-level merging).

#### Scenario: List replacement
- **WHEN** `config.local.yaml` specifies a top-level list key
- **THEN** the merged config SHALL contain exactly the local list for that key, discarding the main config list

### Requirement: Local config excluded from version control
The file `config.local.yaml` SHALL be listed in `.gitignore` and MUST NOT be committed to the repository.

#### Scenario: gitignore entry present
- **WHEN** `.gitignore` is inspected
- **THEN** it SHALL contain an entry matching `config.local.yaml`

### Requirement: Example local config file provided
An example file `config.local.yaml.example` SHALL exist in the project root, demonstrating common override fields (device name, Appium host/port, party ID) with placeholder values.

#### Scenario: Example file exists and is valid YAML
- **WHEN** `config.local.yaml.example` is parsed as YAML
- **THEN** it SHALL parse without errors and contain at least one commented or placeholder override entry
