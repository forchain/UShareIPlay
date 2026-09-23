## ADDED Requirements

### Requirement: Generated managed-device override
The system SHALL generate the managed Virtual Audio Device Appium override in an ignored local configuration file without changing the tracked base configuration.

#### Scenario: Override generation preserves unrelated local settings
- **WHEN** a local configuration file already contains operator-specific settings
- **THEN** managed-device generation SHALL merge only the device and Appium target fields while preserving unrelated local settings
