# User Count Parsing Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update user count parsing to handle "x人在线" format robustly using regex.

**Architecture:** Update `UserCountEvent.handle` with regex-based parsing and add a comprehensive unit test.

**Tech Stack:** Python, `re` module, `pytest`.

---

### Task 1: Create Unit Test for User Count Parsing

**Files:**
- Create: `tests/test_user_count_event.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from ushareiplay.events.user_count import UserCountEvent

@pytest.mark.asyncio
async def test_user_count_parsing_formats():
    event = UserCountEvent()
    mock_wrapper = MagicMock()
    
    test_cases = [
        ("6人", 6),
        ("6人在线", 6), # This will fail with current implementation
        ("123", 123),
        ("在线 10 人", 10),
    ]
    
    with patch("ushareiplay.managers.info_manager.InfoManager.instance") as mock_instance:
        mock_info = MagicMock()
        mock_info.user_count = 0
        mock_info.refresh_online_users = AsyncMock()
        mock_instance.return_value = mock_info
        
        for input_text, expected_count in test_cases:
            mock_wrapper.text = input_text
            mock_info.user_count = -1 # Reset to ensure update
            await event.handle("user_count", mock_wrapper)
            assert mock_info.user_count == expected_count, f"Failed to parse '{input_text}'"

@pytest.mark.asyncio
async def test_user_count_parsing_failure():
    event = UserCountEvent()
    mock_wrapper = MagicMock()
    
    failure_cases = ["", "无数据", "unknown"]
    
    with patch("ushareiplay.managers.info_manager.InfoManager.instance") as mock_instance:
        mock_info = MagicMock()
        mock_info.user_count = 0
        mock_instance.return_value = mock_info
        
        for input_text in failure_cases:
            mock_wrapper.text = input_text
            result = await event.handle("user_count", mock_wrapper)
            assert result is False
            assert mock_info.user_count == 0 # Should not change
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_user_count_event.py`
Expected: FAIL with "Failed to parse '6人在线'"

---

### Task 2: Implement Robust Regex Parsing

**Files:**
- Modify: `src/ushareiplay/events/user_count.py`

- [ ] **Step 1: Update `handle` method**

```python
    async def handle(self, key: str, element_wrapper):
        """
        处理在线人数事件
        
        解析人数文本并更新到 InfoManager
        
        Args:
            key: 触发事件的元素 key，这里是 'user_count'
            element_wrapper: ElementWrapper 实例，包装了在线人数元素
            
        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        try:
            # 获取元素文本
            user_count_text = element_wrapper.text
            if not user_count_text:
                return False

            # 使用正则提取第一个数字序列，例如 "6人", "6人在线", "在线 10 人" -> 6, 6, 10
            match = re.search(r'(\d+)', user_count_text)
            if not match:
                self.logger.warning(f"无法解析人数文本: {user_count_text}")
                return False

            try:
                user_count = int(match.group(1))
            except ValueError:
                self.logger.warning(f"无法将提取的文本转换为整数: {match.group(1)}")
                return False

            # 更新 InfoManager 中的在线人数
            from ushareiplay.managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            if user_count != info_manager.user_count:
                info_manager.user_count = user_count
                await info_manager.refresh_online_users()

            return False

        except Exception as e:
            self.logger.error(f"Error processing user count event: {str(e)}")
            return False
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_user_count_event.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/ushareiplay/events/user_count.py tests/test_user_count_event.py
git commit -m "feat: robustly parse user count with regex to support 'x人在线' format"
```
