#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
sys.path.append('src')

from utils.config_loader import ConfigLoader

# 直接测试日志目录创建功能
def test_log_dir_creation():
    """测试日志目录创建功能"""
    print("测试日志目录创建功能...")
    
    # 加载配置
    config = ConfigLoader.load_config()
    log_dir = config.get('logging', {}).get('directory', 'logs')
    print(f"配置的日志目录: {log_dir}")
    
    # 测试目录创建
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        print(f"✓ 成功创建目录: {log_dir}")
    else:
        print(f"✓ 目录已存在: {log_dir}")
    
    # 测试聊天日志文件创建
    chat_log_file = f'{log_dir}/chat.log'
    try:
        with open(chat_log_file, 'a', encoding='utf-8') as f:
            f.write("测试聊天日志消息\n")
        print(f"✓ 成功写入聊天日志文件: {chat_log_file}")
    except Exception as e:
        print(f"✗ 写入聊天日志文件失败: {e}")
    
    print("\n测试完成!")

if __name__ == "__main__":
    test_log_dir_creation()

def test_chat_logger():
    """测试聊天日志器配置功能"""
    print("测试聊天日志器配置功能...")
    
    # 加载配置
    config = ConfigLoader.load_config()
    log_dir = config.get('logging', {}).get('directory', 'logs')
    print(f"配置的日志目录: {log_dir}")
    
    # 获取聊天日志器
    chat_logger = get_chat_logger(config)
    print(f"聊天日志器: {chat_logger}")
    
    # 测试日志写入
    test_message = "测试聊天日志消息"
    chat_logger.info(test_message)
    print(f"已写入测试消息: {test_message}")
    
    # 检查日志文件是否存在
    log_file = f'{log_dir}/chat.log'
    if os.path.exists(log_file):
        print(f"✓ 日志文件已创建: {log_file}")
        
        # 读取最后一行验证内容
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                print(f"最后一行日志: {last_line}")
                if test_message in last_line:
                    print("✓ 日志内容正确")
                else:
                    print("✗ 日志内容不正确")
    else:
        print(f"✗ 日志文件未创建: {log_file}")
    
    print("\n测试完成!")

if __name__ == "__main__":
    test_chat_logger() 