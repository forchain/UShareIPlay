## ADDED Requirements

### Requirement: Deterministic black-box loopback measurement
The system SHALL verify a Virtual Audio Device by playing a deterministic signal through a standard Android playback API and capturing through a standard Android microphone API.

#### Scenario: Positive loopback run passes objective thresholds
- **WHEN** Host Audio Loopback is enabled and the route is working
- **THEN** the analyzer SHALL report passing correlation, frequency, SNR, and amplitude criteria

### Requirement: Required negative control
The system SHALL run a capture with Host Audio Loopback disabled before it accepts a positive loopback result.

#### Scenario: Disabled host input prevents acceptance
- **WHEN** the negative-control capture meets the positive acceptance criteria
- **THEN** the verifier SHALL report an invalid test and SHALL not report the Virtual Audio Device ready

### Requirement: Retained verification evidence
The system SHALL retain the generated source signal, captured PCM, hashes, command logs, measured metrics, and a machine-readable result for every loopback attempt.

#### Scenario: Operator inspects a completed verification
- **WHEN** a loopback attempt completes
- **THEN** its artifact directory SHALL contain the evidence required to reproduce the analyzer conclusion
