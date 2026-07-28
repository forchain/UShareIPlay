## ADDED Requirements

### Requirement: Verified Linux backend selection
The system SHALL select the Waydroid PipeWire-backed Android runtime on Linux and SHALL fail with an actionable diagnostic on unsupported hosts or missing required backend components. The macOS Android Emulator SHALL NOT be presented as an audio-routing backend.

#### Scenario: macOS operator opens the managed AVD
- **WHEN** a macOS operator opens the managed Android Emulator
- **THEN** the system SHALL keep host microphone injection disabled unless explicitly requested for diagnosis and SHALL not report audio ready

#### Scenario: Linux backend is unavailable
- **WHEN** a Linux operator prepares Host Audio Loopback without an active PipeWire service
- **THEN** the system SHALL report the missing service without reporting audio ready

### Requirement: Dedicated audio routing
The system SHALL use a dedicated Linux virtual source for a Waydroid audio session and SHALL not modify macOS host input defaults.

#### Scenario: Waydroid audio session exits
- **WHEN** a Linux Waydroid audio session exits
- **THEN** the system SHALL remove its owned PipeWire links and record the outcome in its artifacts
