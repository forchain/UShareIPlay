# U Share I Play

A mobile application for Android that monitors Soul App group chat messages and automatically responds to music playback requests.

## Features

- Monitor Soul App group chat messages
- Automatically recognize music playback commands (e.g., ":play 听妈妈的话 周杰伦")
- Automatically switch to the music app (QQ Music) and search and play the specified song
- Send play status messages back to Soul App after successful playback
- Toggle accompaniment mode for karaoke experience

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
git clone https://github.com/yourusername/SoulMusicBox-Android.git
cd SoulMusicBox-Android
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
The `config.yaml` file in the project root directory contains the following configuration:

```yaml
soul:
    package_name: "cn.soulapp.android"
    chat_activity: ".cpnt_voiceparty.soulhouse.SoulHouseActivity"
    elements: # UI elements are defined in the config.yaml file

qq_music:
    package_name: "com.tencent.qqmusic"
    search_activity: ".activity.AppStarterActivity"
    elements: # UI elements are defined in the config.yaml file

commands: # Commands are defined in the config.yaml file

appium:
    host: "0.0.0.0"
    port: 4723

device:
    name: "192.168.50.151:5555"  # Use your phone's IP:PORT
    platform_name: "Android"
    platform_version: "10"
    automation_name: "UiAutomator2"
    no_reset: true
```

The configuration file is divided into several sections:

1. `soul`: Soul App related configuration
   - `package_name`: Soul App package name
   - `chat_activity`: Chat activity path
   - `elements`: UI element identifiers

2. `qq_music`: QQ Music App related configuration
   - `package_name`: QQ Music package name
   - `search_activity`: Search activity path
   - `elements`: UI element identifiers for various features including:
     - Basic playback controls
     - Player panel elements
     - Notification panel controls
     - Lyrics and song info elements
     - Accompaniment mode controls

3. `commands`: Command configurations
   - Multiple command configurations with:
     - `prefix`: Command trigger word (e.g., "play", "skip", "next")
     - `response_template`: Message template for command response
     - `error_template`: Message template for command error

4. `appium`: Appium server configuration
   - `host`: Server host address
   - `port`: Server port number

5. `device`: Device configuration
   - `name`: Device ID
   - `platform_name`: Operating system
   - `platform_version`: OS version
   - `automation_name`: Automation framework name
   - `no_reset`: App reset settings

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
source venv/bin/activate

# Start Appium server
appium

# Open new terminal window and run program
python main.py
```

### 2. Usage Steps
1. Ensure phone screen is unlocked
2. Enter target Soul App group chat
3. Send message using one of the following formats:
   - `:play song_name artist_name`: Play a song
   - `:next song_name artist_name`: Add song to play next
   - `:skip`: Skip to next song
   - `:pause`: Pause/Continue current playback
   - `:vol`: Set volume
   - `:acc 1/0`: Enable/disable accompaniment mode
   - `:mode <mode_name>`: Switch playback mode (0:normal/-1:random/1:single)
   Example: ":play 听妈妈的话 周杰伦" or ":mode 1"
4. Program will automatically:
   - Switch to QQ Music
   - Search and play song
   - Return to Soul and send play status

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

## Development Guide

### 1. Project Structure

```bash
SoulMusicBox-Android/
├── main.py # Main program entry
├── config.yaml # Configuration file
├── requirements.txt # Python dependencies
├── src/
│ ├── soul/ # Soul App related operations
│ ├── music/ # Music App related operations
│ └── utils/ # Utility functions
└── tests/ # Test files
```

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
