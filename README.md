# SoulMusicBox-Android

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
python3 -m venv venv
source venv/bin/activate
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
1. Connect the phone to the computer using a USB data cable
2. Allow USB debugging on the phone
3. Verify connection:

```bash
adb devices
```

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
    elements:
        message_list: "cn.soulapp.android:id/rvMessage"
        message_content: "cn.soulapp.android:id/tvContent"
        input_box_entry: "cn.soulapp.android:id/tvChat"
        input_box: "cn.soulapp.android:id/etInputView"
        button_send: "cn.soulapp.android:id/btnSend"

qq_music:
    package_name: "com.tencent.qqmusic"
    search_activity: ".activity.AppStarterActivity"
    elements:
        search_entry: "//androidx.recyclerview.widget.RecyclerView[@resource-id=\"com.tencent.qqmusic:id/hi2\"]/android.view.View"
        search_box: "com.tencent.qqmusic:id/searchItem"
        play_button: "com.tencent.qqmusic:id/krg"
        next_button: "com.tencent.qqmusic:id/f4"
        player_panel: "com.tencent.qqmusic:id/idm"
        back_button: "//android.widget.ImageButton[@content-desc=\"返回\"]"
        song_name: "com.tencent.qqmusic:id/ll6"
        singer_name: "com.tencent.qqmusic:id/ln9"
        pause_button: "android:id/action1"
        skip_button: "android:id/action2"
        playing_bar: "com.tencent.qqmusic:id/iir"
        current_song: "android:id/title"
        current_singer: "android:id/text"

commands:
    - prefix: "play"
      response_template: "Playing <<{song}>> by {singer}"
    - prefix: "skip"
      response_template: "Skipped to next song <<{song}>> by {singer}"
    - prefix: "next"
      response_template: "Scheduled {song} by {singer} to play next"
    - prefix: "pause"
      response_template: "Paused/Playing <<{song}>> by {singer}"
    - prefix: "vol+"
      response_template: "Volume increased"
    - prefix: "vol-"
      response_template: "Volume decreased"

appium:
    host: "0.0.0.0"
    port: 4723

device:
    name: "your_device_name"  # Replace with actual device ID
    platform_name: "Android"
    platform_version: "10"  # Replace with actual Android version
    automation_name: "UiAutomator2"
    no_reset: true
```

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
   - `play song_name artist_name`: Play a song
   - `skip song_name artist_name`: Skip to a specific song
   - `next song_name artist_name`: Add song to play next
   - `pause`: Pause current playback
   - `vol+`: Increase volume
   - `vol-`: Decrease volume
   - `accompaniment 1/0`: Enable/disable accompaniment mode
   Example: "play 听妈妈的话 周杰伦" or "accompaniment on"
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
