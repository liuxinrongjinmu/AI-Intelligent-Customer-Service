"""
pytest 全局配置：设置项目根目录为 Python path 根目录
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))