"""应用路径工具：统一管理打包与用户目录下的配置路径。"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

APP_DIR_NAME = 'QQFarmCopilot'
_USER_CONFIG_COPY_EXCLUDES = {'config.template.json', 'plants.json', 'ui_labels.json', 'button_aliases.json'}


def _project_root() -> Path:
    """返回源码模式下的项目根目录。"""
    return Path(__file__).resolve().parent.parent


def bundled_root_dir() -> Path:
    """返回运行时资源根目录（源码根目录或 PyInstaller 临时目录）。"""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            return Path(str(meipass))
    return _project_root()


def bundled_configs_dir() -> Path:
    """返回打包内置的 configs 目录。"""
    return bundled_root_dir() / 'configs'


def user_app_dir() -> Path:
    """返回 Windows 标准用户应用目录。"""
    if sys.platform == 'win32':
        base = os.getenv('APPDATA') or os.getenv('LOCALAPPDATA')
        if base:
            return Path(base) / APP_DIR_NAME
        return Path.home() / 'AppData' / 'Roaming' / APP_DIR_NAME
    return Path.home() / f'.{APP_DIR_NAME}'


def user_configs_dir() -> Path:
    """返回用户可写 configs 目录。"""
    return user_app_dir() / 'configs'


def ensure_user_configs() -> Path:
    """确保用户目录存在默认配置文件（不存在才复制）。"""
    dst_dir = user_configs_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_dir = bundled_configs_dir()
    if not src_dir.exists() or not src_dir.is_dir():
        return dst_dir

    for src in src_dir.glob('*.json'):
        if src.name in _USER_CONFIG_COPY_EXCLUDES:
            continue
        dst = dst_dir / src.name
        if dst.exists():
            continue
        try:
            shutil.copy2(src, dst)
        except Exception:
            continue
    return dst_dir


def resolve_config_file(filename: str, prefer_user: bool = True) -> Path:
    """解析配置文件路径：默认优先用户目录，缺失时回退内置目录。"""
    name = str(filename or '').strip().replace('\\', '/').split('/')[-1]
    if not name:
        return user_configs_dir() / filename

    if prefer_user:
        user_file = user_configs_dir() / name
        if user_file.exists():
            return user_file

    bundled_file = bundled_configs_dir() / name
    if bundled_file.exists():
        return bundled_file

    return user_configs_dir() / name


def resolve_runtime_path(*parts: str) -> Path:
    """返回运行时资源目录下的相对路径。"""
    return bundled_root_dir().joinpath(*parts)


def load_config_json(filename: str, prefer_user: bool = True) -> Any:
    """按统一路径规则读取配置 JSON。"""
    path = resolve_config_file(filename, prefer_user=prefer_user)
    if not path.exists():
        raise FileNotFoundError(f'config json not found: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def load_config_json_object(filename: str, prefer_user: bool = True) -> dict[str, Any]:
    """读取配置 JSON，并要求根节点为对象。"""
    path = resolve_config_file(filename, prefer_user=prefer_user)
    data = load_config_json(filename, prefer_user=prefer_user)
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} root must be object: {path}')
    return data


def load_config_json_array(filename: str, prefer_user: bool = True) -> list[Any]:
    """读取配置 JSON，并要求根节点为数组。"""
    path = resolve_config_file(filename, prefer_user=prefer_user)
    data = load_config_json(filename, prefer_user=prefer_user)
    if not isinstance(data, list):
        raise ValueError(f'{path.name} root must be array: {path}')
    return data
