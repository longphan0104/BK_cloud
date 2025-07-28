# utils.py
import os
import sys

def resource_path(relative_path):
    """Lấy đường dẫn đúng đến file khi chạy dạng exe hoặc script gốc"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)
