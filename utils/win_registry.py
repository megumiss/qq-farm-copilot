"""Windows 注册表公共读写方法。"""

from __future__ import annotations

import winreg


def read_current_user_string(subkey: str, name: str) -> str | None:
    """读取 HKCU 下的字符串值。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, str(subkey), 0, winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, str(name))
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def write_current_user_string(subkey: str, name: str, value: str) -> bool:
    """写入 HKCU 下的字符串值。"""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, str(subkey)) as key:
            winreg.SetValueEx(key, str(name), 0, winreg.REG_SZ, str(value))
        return True
    except Exception:
        return False
