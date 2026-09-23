## ADDED Requirements

### Requirement: Managed default Virtual Audio Device
The system SHALL provision and start a visible ARM64 Play Store AVD named `ushareiplay-audio` without removing applications or account state from an existing instance.

#### Scenario: First launch provisions the default AVD
- **WHEN** an operator starts the default Virtual Audio Device and its required image or AVD does not exist
- **THEN** the system SHALL install or create only the required named resources and open the AVD

#### Scenario: Repeat launch preserves manual installation state
- **WHEN** an operator starts an existing default Virtual Audio Device
- **THEN** the system SHALL open the existing AVD without wiping its data

### Requirement: Appium target integration
The system SHALL generate an ignored local configuration override targeting the active managed emulator serial, localhost Appium, UiAutomator2, and no-reset behavior.

#### Scenario: Managed AVD becomes the Appium target
- **WHEN** a managed Virtual Audio Device is running
- **THEN** the generated local override SHALL target that emulator without changing the tracked base configuration

### Requirement: Disposable Root Fallback
The system SHALL keep any root-capable Android runtime separate from the macOS UI AVD and SHALL only make it available on Linux after retained standard-route failure evidence exists.

#### Scenario: Root investigation is requested before standard evidence exists
- **WHEN** an operator requests a root investigation without a failed standard verification report
- **THEN** the system SHALL refuse to start it and identify the missing evidence

#### Scenario: Root investigation is requested on an unsupported host
- **WHEN** an operator requests a root investigation on macOS
- **THEN** the system SHALL refuse to start it and identify Linux as the required host
