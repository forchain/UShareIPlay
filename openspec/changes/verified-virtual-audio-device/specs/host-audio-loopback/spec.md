## ADDED Requirements

### Requirement: Supported host-audio backend selection
The system SHALL select BlackHole 2ch on macOS and PipeWire on Linux, and SHALL fail with an actionable diagnostic on unsupported hosts or missing required backend components.

#### Scenario: macOS backend is unavailable
- **WHEN** a macOS operator prepares Host Audio Loopback without BlackHole 2ch available
- **THEN** the system SHALL report installation and restart requirements without reporting audio ready

#### Scenario: Linux backend is unavailable
- **WHEN** a Linux operator prepares Host Audio Loopback without an active PipeWire service
- **THEN** the system SHALL report the missing service without reporting audio ready

### Requirement: Host audio settings are restored
The system SHALL restore the host audio-device defaults it changed after a managed session stops or fails.

#### Scenario: Managed session exits
- **WHEN** a managed session that changed host audio defaults exits
- **THEN** the system SHALL attempt restoration and record the outcome in its artifacts
