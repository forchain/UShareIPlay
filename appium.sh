#!/bin/bash
adb connect 192.168.8.151:5555
appium --allow-insecure=adb_shell,chromedriver_autodownload
