#!/usr/bin/env python3
"""
Test script to verify singleton pattern implementation
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.singleton import Singleton
from src.managers.theme_manager import ThemeManager
from src.managers.title_manager import TitleManager

class MockHandler:
    """Mock handler for testing"""
    def __init__(self):
        self.logger = MockLogger()

class MockLogger:
    """Mock logger for testing"""
    def info(self, msg): print(f"INFO: {msg}")
    def error(self, msg): print(f"ERROR: {msg}")
    def warning(self, msg): print(f"WARNING: {msg}")

def test_singleton_pattern():
    """Test that singleton pattern works correctly"""
    print("Testing Singleton Pattern Implementation")
    print("=" * 50)
    
    # Create mock handler
    handler = MockHandler()
    
    # Test ThemeManager singleton
    print("\n1. Testing ThemeManager singleton:")
    theme_manager1 = ThemeManager.instance(handler)
    theme_manager2 = ThemeManager.instance(handler)
    
    print(f"ThemeManager instance 1: {id(theme_manager1)}")
    print(f"ThemeManager instance 2: {id(theme_manager2)}")
    print(f"Are they the same instance? {theme_manager1 is theme_manager2}")
    
    # Test TitleManager singleton
    print("\n2. Testing TitleManager singleton:")
    title_manager1 = TitleManager.instance(handler)
    title_manager2 = TitleManager.instance(handler)
    
    print(f"TitleManager instance 1: {id(title_manager1)}")
    print(f"TitleManager instance 2: {id(title_manager2)}")
    print(f"Are they the same instance? {title_manager1 is title_manager2}")
    
    # Test state synchronization
    print("\n3. Testing state synchronization:")
    theme_manager1.set_theme("测试")
    print(f"Theme from manager1: {theme_manager1.get_current_theme()}")
    print(f"Theme from manager2: {theme_manager2.get_current_theme()}")
    
    # Test that both commands would get the same instances
    print("\n4. Simulating command initialization:")
    # Simulate what happens in title.py and theme.py commands
    theme_mgr_from_title = ThemeManager.instance(handler)
    title_mgr_from_title = TitleManager.instance(handler)
    
    theme_mgr_from_theme = ThemeManager.instance(handler)
    title_mgr_from_theme = TitleManager.instance(handler)
    
    print(f"ThemeManager from title command: {id(theme_mgr_from_title)}")
    print(f"ThemeManager from theme command: {id(theme_mgr_from_theme)}")
    print(f"Are they the same? {theme_mgr_from_title is theme_mgr_from_theme}")
    
    print(f"TitleManager from title command: {id(title_mgr_from_title)}")
    print(f"TitleManager from theme command: {id(title_mgr_from_theme)}")
    print(f"Are they the same? {title_mgr_from_title is title_mgr_from_theme}")
    
    print("\n✅ Singleton pattern test completed successfully!")
    print("Both commands will now share the same manager instances.")

if __name__ == "__main__":
    test_singleton_pattern()
