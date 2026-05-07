from __future__ import annotations

from typing import Optional, Tuple

from selenium.webdriver.remote.webelement import WebElement


class Navigator:
    def __init__(self, owner):
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.owner, name)

    @property
    def driver(self):
        return self.owner.driver

    @property
    def config(self):
        return self.owner.config

    @property
    def logger(self):
        return self.owner.logger

    def navigate_to_element(
            self,
            target_key: str,
            interference_keys: list = None,
            home_key: str = "home_nav",
            back_keys=None,
            max_attempts: int = 10,
    ) -> Tuple[Optional[str], Optional[WebElement]]:
        """
        导航到目标元素，通过检测当前页面状态并执行相应操作

        Args:
            home_key: 首页元素key，找到表示已回到首页，不能再返回
            back_keys: 返回按钮key列表，找到则点击返回上一页
            target_key: 目标元素key，找到则直接返回
            interference_keys: 干扰元素key列表，出现则按系统返回键隐藏
            max_attempts: 最大尝试次数，防止无限循环

        Returns:
            (key, element): 找到的元素key和元素对象
            (None, None): 未找到或出错时返回
        """
        if back_keys is None:
            back_keys = ["go_back", "minimize_screen"]
        if interference_keys is None:
            interference_keys = []

        self.logger.info(f"开始导航到目标元素: {target_key}")
        self.press_back()

        for attempt in range(max_attempts):
            self.logger.debug(f"导航尝试 {attempt + 1}/{max_attempts}")

            # 构建检测元素列表，按优先级排序：干扰元素 -> 目标元素 -> 返回按钮 -> home元素
            check_keys = interference_keys + [target_key] + back_keys + [home_key]

            # 使用 wait_for_any_element_plus 检测当前状态
            found_key, found_element = self.wait_for_any_element_plus(check_keys)

            if not found_element:
                self.logger.warning(f"第 {attempt + 1} 次尝试：未检测到任何元素")
                # 按系统返回键尝试返回
                self.press_back()
                return None, None

            # 根据找到的元素类型执行相应操作
            if found_key == target_key:
                # 命中目标后仅做干扰元素复核（无等待），避免误判后直接返回
                interference_key, interference_element = self.try_find_any_element_plus(interference_keys)
                if interference_element:
                    self.logger.info(
                        f"命中目标 {target_key} 后发现干扰元素 {interference_key}，先按返回键关闭后重试确认"
                    )
                    if not self.press_back():
                        self.logger.error("按系统返回键失败")
                        return None, None
                    continue

                self.logger.info(f"找到目标元素: {target_key}（已通过二次确认）")
                return found_key, found_element

            elif found_key in back_keys:
                if self.click_element_at(found_element):
                    self.logger.info(f"找到返回按钮: {found_key}，点击返回")
                else:
                    self.logger.warning(f"点击返回按钮失败: {found_key}")
                    # 尝试系统返回键作为备选
                    self.press_back()

            elif found_key in interference_keys:
                self.logger.info(f"发现干扰元素: {found_key}，按系统返回键隐藏")
                if not self.press_back():
                    self.logger.error("按系统返回键失败")
                    return None, None

            elif found_key == home_key:
                self.logger.info(f"已回到首页: {home_key}，无法继续返回")
                return found_key, found_element

            else:
                self.logger.warning(f"检测到未知元素: {found_key}")
                self.press_back()
                return None, None

        # 达到最大尝试次数
        self.logger.error(f"导航失败：达到最大尝试次数 {max_attempts}")
        return None, None
