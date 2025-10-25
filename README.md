# U Share I Play

An intelligent Android automation system that transforms Soul App party rooms into fully automated music management platforms. The system provides comprehensive music control, room administration, user management, and interactive features through a sophisticated command-driven architecture.

## ✨ Key Features

### 🎵 **Intelligent Music Management**
- **Smart Playback Control**: Automatically play songs, albums, playlists, and artist collections
- **Advanced Playback Features**: Volume control, play mode switching, quality detection
- **KTV Experience**: Lyrics recognition with Tesseract OCR and accompaniment mode
- **Music Quality Control**: Automatic detection and handling of low-quality tracks

### 🎤 **Comprehensive Room Administration**
- **Dynamic Room Management**: Real-time room title, topic, theme, and notice updates
- **Smart Theme System**: Customizable room themes with automatic UI synchronization
- **Advanced Seat Management**: Reservation system with user levels and permissions
- **User Administration**: Role-based access control and user level management

### 🤖 **Advanced Automation & Intelligence**
- **Command Processing**: 20+ intelligent commands with parameter validation
- **Timer System**: Scheduled tasks and recurring commands with database persistence
- **Crash Recovery**: Automatic error detection and recovery from app crashes
- **Database Integration**: SQLite with Tortoise ORM for persistent data storage

### 🎯 **Interactive Social Features**
- **Greeting System**: Automated user greetings with custom messages and songs
- **Mic Management**: Intelligent microphone control based on playback state
- **Focus Tracking**: Real-time monitoring of user activity and engagement
- **Party Management**: Room creation, joining, and comprehensive administration

### 🔧 **Enterprise-Grade Architecture**
- **Modular Design**: Manager-based architecture with clear separation of concerns
- **Singleton Pattern**: Efficient resource management across all components
- **Async Processing**: Non-blocking operations with message queuing
- **Extensible Framework**: Easy to add new commands and features

## Environment Requirements

- macOS system
- Python 3.7+
- Android device or emulator
- Java Development Kit (JDK) 8+
- Android SDK
- Node.js 12+
- Appium Server
- QQ Music App
- Soul App

## Environment Setup

### 1. Install Python and Create Virtual Environment

```bash
brew install python
python3 --version

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install JDK

```bash
brew install --cask adoptopenjdk8
java -version
javac -version
```

### 3. Install Android SDK

1. Download and install [Android Studio](https://developer.android.com/studio)
2. Open Android Studio, go to Settings/Preferences -> Appearance & Behavior -> System Settings -> Android SDK
3. In the SDK Platforms tab, select the following:
   - Android 11.0 (API Level 30)
   - Android 10.0 (API Level 29)
4. In the SDK Tools tab, ensure the following are installed:
   - Android SDK Build-Tools
   - Android SDK Platform-Tools
   - Android SDK Tools
   - Intel x86 Emulator Accelerator (HAXM installer)

5. Configure environment variables by adding the following to `~/.zshrc` or `~/.bash_profile`:

```bash
export ANDROID_HOME=$HOME/Library/Android/sdk
export PATH=$PATH:$ANDROID_HOME/tools
export PATH=$PATH:$ANDROID_HOME/tools/bin
export PATH=$PATH:$ANDROID_HOME/platform-tools
```

6. Activate the environment variables:

```bash
source ~/.zshrc # or source ~/.bash_profile
```

### 4. Install Node.js and Appium

```bash
brew install node
node --version
npm --version
npm install -g appium
npm install -g appium-doctor
appium-doctor --android
```

### 5. Install project dependencies

```bash
git clone https://github.com/yourusername/UShareIPlay.git
cd UShareIPlay
# Ensure venv is activated
source venv/bin/activate
pip install -r requirements.txt
```

### 6. Install Tesseract OCR

For KTV mode lyrics recognition, you need to install Tesseract OCR:

#### macOS
```bash
# Install Tesseract using Homebrew
brew install tesseract
brew install tesseract-lang  # Install additional language packs

# Verify installation
tesseract --version

# Install Python binding
pip install pytesseract Pillow
```

#### Verify Chinese Support
```bash
# Check available languages
tesseract --list-langs

# Should include:
# chi_sim - Simplified Chinese
# chi_tra - Traditional Chinese
# eng - English
```

If Chinese languages are missing, install them:
```bash
brew install tesseract-lang
```

#### Configure Tesseract Path
Add the following to your environment variables (in `~/.zshrc` or `~/.bash_profile`):
```bash
export TESSDATA_PREFIX=/usr/local/share/tessdata
```

Then reload your shell:
```bash
source ~/.zshrc  # or source ~/.bash_profile
```

## Phone Configuration

### 1. Enable Developer Options
1. Go to Settings -> About phone
2. Find the "Version number" option (different phones may be located differently)
3. Tap the version number 7 times until the developer options are enabled
4. Return to the main settings page and find "Developer options"
5. Enable the following options:
   - USB debugging
   - USB installation
   - Stay awake

### 2. Connect Device

#### USB Connection
1. Connect the phone to the computer using a USB data cable
2. Allow USB debugging on the phone
3. Verify connection:
```bash
adb devices
```

#### Wireless Connection
1. First connect your device via USB and ensure USB debugging is enabled
2. Make sure your phone and computer are on the same network
3. Get your phone's IP address:
   - Go to Settings -> About phone -> Status -> IP address
   - Or use command: `adb shell ip addr show wlan0`
4. Enable wireless debugging:
```bash
# Enable TCP/IP mode
adb tcpip 5555

# Connect to device wirelessly
adb connect <phone-ip-address>:5555

# Verify connection
adb devices
# Should show something like:
# 192.168.50.151:5555    device
```

5. You can now unplug the USB cable

Troubleshooting wireless connection:
- If connection fails, try:
```bash
# Reset ADB server
adb kill-server
adb start-server

# Reconnect
adb connect <phone-ip-address>:5555
```
- Ensure phone and computer are on same network
- Check if any firewall is blocking port 5555
- Try re-enabling wireless debugging through USB connection

### 3. Application Preparation
1. Install Soul App and log in
2. Install QQ Music App and log in
3. Ensure both applications have the necessary permissions

## Project Configuration

### 1. Configuration File Description
The `config.yaml` file contains comprehensive configuration for the entire system:

```yaml
# Soul App Configuration
soul:
    package_name: "cn.soulapp.android"
  chat_activity: ".component.startup.main.MainActivity"
  default_party_id: "FM15321640"
  default_notice: "U Share I Play\n分享音乐 享受快乐"
  
  # Initial scheduled timers
  initial_timers:
    - id: "playlist_sleep"
      time: "00:00"
      message: "playlist Lofi Girl 官方"
      repeat: true
    # ... more timers
  
  # UI element identifiers for Soul App
  elements:
    message_list: "cn.soulapp.android:id/rvMessage"
    message_content: "cn.soulapp.android:id/tvContent"
    # ... 100+ element definitions

# QQ Music App Configuration  
qq_music:
    package_name: "com.tencent.qqmusic"
    search_activity: ".activity.AppStarterActivity"
  
  # UI element identifiers for QQ Music
  elements:
    search_entry: "com.tencent.qqmusic:id/sub_edit_text"
    # ... 80+ element definitions

# Command System Configuration
commands:
  - prefix: "play"
    response_template: "Playing {song} by {singer} in {album}"
    error_template: "Failed to play music, because {error}"
  - prefix: "vol"
    response_template: "{message}"
    error_template: "Failed to adjust volume, because {error}"
  # ... 20+ command configurations

# Appium Server Configuration
appium:
  host: "192.168.50.103"
    port: 4723

# Device Configuration
device:
  name: "192.168.50.151:5555"
    platform_name: "Android"
    platform_version: "10"
    automation_name: "UiAutomator2"
    no_reset: true

# Logging Configuration
logging:
  directory: "../logs"
```

### 2. Configuration Sections Explained

#### **Soul App Configuration**
- **`package_name`**: Soul App package identifier
- **`chat_activity`**: Main chat activity class
- **`default_party_id`**: Default party room ID to join
- **`default_notice`**: Default room announcement
- **`initial_timers`**: Scheduled tasks that run automatically
- **`elements`**: 100+ UI element identifiers for Soul App automation

#### **QQ Music App Configuration**
- **`package_name`**: QQ Music package identifier
- **`search_activity`**: Search interface activity
- **`elements`**: 80+ UI element identifiers for music app automation

#### **Command System Configuration**
- **`prefix`**: Command trigger word (e.g., "play", "skip", "vol")
- **`response_template`**: Success message template with variables
- **`error_template`**: Error message template
- **Variables**: `{song}`, `{singer}`, `{album}`, `{volume}`, `{message}`, etc.

#### **System Configuration**
- **`appium`**: Server connection settings
- **`device`**: Android device connection parameters
- **`logging`**: Log file storage location

### 3. Key Configuration Features

#### **Timer System**
```yaml
initial_timers:
  - id: "playlist_morning"
    time: "09:00"
    message: "playlist 早安音乐"
    repeat: true
  - id: "theme_evening"
    time: "20:00"
    message: "theme 夜曲"
    repeat: true
```

#### **Command Templates**
```yaml
- prefix: "play"
  response_template: "Playing {song} by {singer} in {album}"
  error_template: "Failed to play music, because {error}"

- prefix: "vol"
  response_template: "{message}"
  error_template: "Failed to adjust volume, because {error}"
```

#### **Element Management**
- **Soul App**: 100+ elements for chat, room management, user interaction
- **QQ Music**: 80+ elements for music playback, lyrics, accompaniment
- **Dynamic Updates**: Elements can be updated via Appium Inspector

### 2. Device Configuration

Before running the program, you need to configure the device information correctly:

1. Get the device ID:
```bash
# List connected devices
adb devices

# Output example:
List of devices attached
XXXXXXXX    device  # XXXXXXXX is the device ID
```

2. Get the Android version:
```bash
adb shell getprop ro.build.version.release
```

3. Update the configuration file:
   - Replace the obtained device ID in the `config.yaml` `device.name` field
   - Replace the Android version number in the `device.platform_version` field

### 3. Custom Configuration
In addition to the required device configuration, you can customize:
- Command prefix
- Response message template
- Target app package names and activities
- Appium server configuration

## Usage Guide

### 1. Start Service

```bash
# Activate virtual environment if not already activated
source .venv/bin/activate

# Start Appium server
appium

# Open new terminal window and run program
python main.py
```

### 2. Available Commands

The system supports 20+ commands for comprehensive room and music management:

#### 🎵 Music Control Commands
- `:play <song> <artist>` - Play specific song immediately
- `:next <song> <artist>` - Add song to playlist queue
- `:skip` - Skip to next song in playlist
- `:pause [0/1]` - Pause (1) or resume (0) playback
- `:vol [0-15]` - Set volume level (no parameter shows current volume)
- `:mode [0/1/-1]` - Set play mode (0:normal, 1:single, -1:random)

#### 📀 Content Management Commands
- `:playlist <name>` - Play specific playlist
- `:singer <name>` - Play all songs by artist
- `:album <name>` - Play entire album
- `:lyrics [groups]` - Display song lyrics (optional group count)
- `:info` - Show current playback information

#### 🎤 Room Management Commands
- `:theme <name>` - Set room theme (max 2 characters)
- `:title <name>` - Set room title
- `:topic <name>` - Set room topic
- `:notice <message>` - Set room announcement

#### 🔧 Advanced Feature Commands
- `:acc [0/1]` - Toggle accompaniment mode for karaoke
- `:ktv [0/1]` - Toggle KTV mode with lyrics recognition
- `:mic [0/1]` - Control microphone (1:on, 0:off)
- `:seat [0/1 <number>|2 <number>]` - Seat management system
- `:timer <command>` - Timer and scheduling system
- `:hello <user> "<message>" "<song>"` - Greeting system
- `:admin [0/1]` - Admin role management
- `:enable [0/1]` - Recovery system control
- `:pack` - Open luck packs (auto-triggered when room has 5+ users)
- `:end` - End party (requires owner's friend)
- `:invite <party_id>` - Invite users to specific party

### 3. Command Examples

```bash
# Basic music playback
:play 听妈妈的话 周杰伦
:playlist 经典老歌
:singer 邓丽君

# Room customization
:theme 音乐
:title 怀旧金曲
:topic 经典老歌分享
:notice 欢迎来到音乐分享房间！

# Advanced features
:vol 8                    # Set volume to 8
:vol                      # Show current volume
:acc 1                    # Enable accompaniment mode
:ktv 1                    # Enable KTV mode
:mic 0                    # Turn off microphone
:seat 1 5                 # Reserve seat number 5
:seat 2 5                 # Sit at seat number 5 immediately

# Timer system
:timer add morning 08:00 "早上好！" repeat
:timer add reminder 14:30 "下午茶时间" repeat
:timer list               # List all timers
:timer remove morning     # Remove timer

# Greeting system
:hello 张三 "欢迎回来" "朋友"

# Admin and management
:admin 1                  # Enable admin mode
:enable 1                 # Enable recovery system
:end                      # End the party
```

### 4. Usage Steps
1. Ensure phone screen is unlocked and both apps are installed
2. Enter target Soul App group chat room
3. Send commands using the format `:command [parameters]`
4. System will automatically:
   - Parse and validate commands
   - Switch between Soul App and QQ Music as needed
   - Execute requested operations
   - Send status messages back to the chat
   - Handle errors gracefully with recovery mechanisms

## Common Issues and Solutions

### 1. Appium Connection Issues
- Error: Device not found

```bash
# Check device connection
adb devices
# Restart adb server
adb kill-server
adb start-server
```

- Error: Session creation failed
  - Check if Appium server is running normally
  - Verify if USB debugging is enabled on the device
  - Run `appium-doctor` to check the environment

### 2. Application Issues
- Element not found
  - Confirm if the app version supports the element
  - Check if the element positioning strategy is correct
  - Use Appium Inspector to verify the element

- Permission issues
  - Ensure the app has the necessary permissions
  - Check Android system permission settings

### 3. Get Application Information
- Get the current running app package name and activity:
```bash
adb shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'
```

- List all installed app package names:
```bash
# List all installed app package names
adb shell pm list packages

# Use grep to filter specific apps
adb shell pm list packages | grep qq
```

- Monitor app activity changes in real-time:
```bash
# Method 1: Monitor ActivityManager
adb shell logcat | grep "ActivityManager"

# Method 2: Monitor activity components more precisely
adb shell logcat | grep "cmp="
```

After obtaining the package name and activity, update the corresponding `package_name` and `activity` fields in the `config.yaml` file.

### 4. UiAutomator2 Crash Recovery
The application now includes automatic recovery from UiAutomator2 server crashes. When the UiAutomator2 instrumentation process crashes, the system will:

1. **Detect the crash** - Automatically identify UiAutomator2 server crashes from error messages
2. **Reinitialize the driver** - Close the current driver session and create a new one
3. **Update references** - Update all handler references to use the new driver
4. **Switch back to app** - Automatically switch back to the target application
5. **Retry operations** - Retry the original operation that caused the crash

**Recovery is implemented in the following methods:**
- `wait_for_element_clickable_plus()` - Element waiting operations
- `wait_for_element_plus()` - Element presence detection
- `try_find_element_plus()` - Element finding operations
- `press_back()` - Back button operations
- `switch_to_app()` - App switching operations
- `wait_for_any_element_plus()` - Multi-element detection

**Log messages to look for:**
- `"Detected UiAutomator2 server crash, attempting recovery..."`
- `"Driver reinitialization completed successfully"`
- `"Found element after recovery"`

If recovery fails multiple times, the system will log error messages and continue operation.

## Development Guide

### 1. Project Structure

```bash
UShareIPlay/
├── main.py                    # Main application entry point
├── config.yaml               # Comprehensive configuration file
├── requirements.txt          # Python dependencies
├── appium.sh                # Appium server startup script
├── run.sh                   # Application startup script
├── data/                    # Database storage
│   └── soul_bot.db          # SQLite database
├── logs/                    # Application logs
├── docs/                    # Documentation
│   ├── command-architecture-principles.md
│   ├── manager-architecture.md
│   ├── theme-command.md
│   └── ...                  # Additional documentation
├── src/
│   ├── core/                # Core system components
│   │   ├── app_controller.py    # Main application controller
│   │   ├── app_handler.py       # Base UI automation handler
│   │   ├── base_command.py      # Abstract command base class
│   │   ├── command_parser.py    # Command parsing logic
│   │   ├── config_loader.py     # Configuration management
│   │   ├── db_manager.py        # Database connection manager
│   │   ├── db_service.py        # Database operations
│   │   ├── message_queue.py     # Async message handling
│   │   └── singleton.py         # Singleton pattern implementation
│   ├── handlers/            # App-specific automation handlers
│   │   ├── qq_music_handler.py  # QQ Music app automation
│   │   └── soul_handler.py      # Soul app automation
│   ├── managers/            # Business logic managers
│   │   ├── admin_manager.py     # User administration
│   │   ├── command_manager.py   # Command processing
│   │   ├── greeting_manager.py  # User greeting system
│   │   ├── message_manager.py   # Message processing
│   │   ├── mic_manager.py       # Microphone control
│   │   ├── music_manager.py     # Music playback management
│   │   ├── notice_manager.py    # Room notice management
│   │   ├── recovery_manager.py  # Error recovery system
│   │   ├── seat_manager/        # Seat management system
│   │   │   ├── __init__.py      # Seat manager initialization
│   │   │   ├── base.py          # Base seat manager
│   │   │   ├── focus.py         # Focus tracking
│   │   │   ├── reservation.py   # Seat reservations
│   │   │   ├── seat_check.py    # Seat validation
│   │   │   ├── seat_ui.py       # UI interactions
│   │   │   └── seating.py       # Seating logic
│   │   ├── theme_manager.py     # Room theme management
│   │   ├── timer_manager.py     # Scheduled tasks
│   │   ├── title_manager.py     # Room title management
│   │   └── topic_manager.py     # Room topic management
│   ├── commands/            # Command implementations (20+ commands)
│   │   ├── acc.py           # Accompaniment mode
│   │   ├── admin.py         # Admin management
│   │   ├── album.py         # Album playback
│   │   ├── enable.py        # Recovery system control
│   │   ├── end.py           # Party termination
│   │   ├── hello.py         # User greeting
│   │   ├── help.py          # Help system
│   │   ├── info.py          # Playback information
│   │   ├── invite.py        # Party invitations
│   │   ├── ktv.py           # KTV mode
│   │   ├── lyrics.py        # Lyrics display
│   │   ├── mic.py           # Microphone control
│   │   ├── mode.py          # Play mode switching
│   │   ├── next.py          # Add to playlist
│   │   ├── notice.py        # Room notice
│   │   ├── pack.py          # Luck pack opening
│   │   ├── pause.py         # Playback control
│   │   ├── play.py          # Music playback
│   │   ├── playlist.py      # Playlist management
│   │   ├── seat.py          # Seat management
│   │   ├── singer.py        # Artist playback
│   │   ├── skip.py          # Skip songs
│   │   ├── theme.py         # Room theme
│   │   ├── timer.py         # Timer management
│   │   ├── title.py         # Room title
│   │   ├── topic.py         # Room topic
│   │   └── vol.py           # Volume control
│   ├── models/              # Data models
│   │   ├── __init__.py      # Models initialization
│   │   ├── seat_reservation.py  # Seat reservation model
│   │   └── user.py          # User model
│   ├── dal/                 # Data access layer
│   │   ├── __init__.py      # DAL initialization
│   │   ├── seat_reservation_dao.py  # Seat reservation DAO
│   │   └── user_dao.py      # User DAO
│   └── helpers/             # Utility helpers
│       └── playlist_parser.py   # Playlist parsing logic
└── test_*.py                # Test files
```

### 2. Architecture Overview

The system follows a **modular, manager-based architecture** with clear separation of concerns:

#### **Core Components (`src/core/`)**
- **`AppController`**: Main application controller using Singleton pattern
- **`AppHandler`**: Base class for UI automation with crash recovery
- **`BaseCommand`**: Abstract base for all command implementations
- **`CommandParser`**: Intelligent command parsing and validation
- **`ConfigLoader`**: YAML configuration management
- **`DatabaseManager`**: SQLite database connection management
- **`MessageQueue`**: Async message processing system
- **`Singleton`**: Thread-safe singleton pattern implementation

#### **Handlers (`src/handlers/`)**
- **`QQMusicHandler`**: QQ Music app automation and music operations
- **`SoulHandler`**: Soul app automation and chat management

#### **Managers (`src/managers/`)**
- **`CommandManager`**: Dynamic command loading and processing
- **`MusicManager`**: Music playback and volume control
- **`SeatManager`**: Advanced seat reservation system with sub-managers
- **`TimerManager`**: Scheduled task execution system
- **`ThemeManager`**: Room theme management with UI synchronization
- **`TitleManager`**: Room title management with cooldown system
- **`TopicManager`**: Room topic management
- **`NoticeManager`**: Room announcement management
- **`AdminManager`**: User administration and permissions
- **`GreetingManager`**: Automated user greeting system
- **`MessageManager`**: Message processing and user interaction
- **`MicManager`**: Microphone control automation
- **`RecoveryManager`**: Error detection and recovery system

#### **Commands (`src/commands/`)**
- **20+ command implementations** for comprehensive functionality
- Each command inherits from `BaseCommand` and implements `process()` method
- Commands handle music control, room management, advanced features

#### **Data Layer (`src/models/`, `src/dal/`)**
- **Tortoise ORM** integration for database operations
- **User model**: User information and level management
- **SeatReservation model**: Seat booking system
- **DAO pattern**: Clean separation of data access logic

### 3. Key Design Patterns

- **Singleton Pattern**: All managers use singleton for resource efficiency
- **Command Pattern**: Commands are modular and easily extensible
- **Manager Pattern**: Business logic separated into specialized managers
- **DAO Pattern**: Clean data access layer separation
- **Observer Pattern**: Event-driven updates and notifications
- **Strategy Pattern**: Different handling strategies for various scenarios

### 2. Development Suggestions

#### Using Appium Inspector
1. Install Appium Inspector
```bash
# Download from GitHub releases
https://github.com/appium/appium-inspector/releases

# Or install via brew (macOS)
brew install --cask appium-inspector
```

2. Configure Appium Inspector
- Launch Appium Inspector
- Configure Desired Capabilities:
  ```json
  {
    "platformName": "Android",
    "deviceName": "your_device_id",
    "platformVersion": "your_android_version",
    "automationName": "UiAutomator2",
    "noReset": true
  }
  ```

3. Using Inspector
- Ensure Appium server is running
- Connect your Android device
- Start the application you want to inspect
- Click "Start Session" in Appium Inspector
- Use the element picker to:
  - Click elements to view their attributes
  - Get element locators (id, xpath, etc.)
  - Record element hierarchies
  - Test interactions with elements

4. Tips for Element Inspection
- Use the refresh button to update the page view
- Try different locator strategies (id, xpath, accessibility id)
- Save commonly used locators for future reference
- Use the recorded element attributes in your config.yaml file

- Use Appium Inspector for element positioning assistance
- Write test cases to ensure functionality stability
- Follow the project's code style

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file
