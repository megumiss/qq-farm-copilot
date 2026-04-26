"""应用路径工具：统一管理打包与用户目录下的配置路径。"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.win_registry import read_current_user_string, write_current_user_string

APP_DIR_NAME = 'QQFarmCopilot'
INSTANCES_DIR_NAME = 'instances'
PROFILES_META_FILENAME = 'profiles.json'
APP_SETTINGS_FILENAME = 'app_settings.json'
_USER_CONFIG_COPY_EXCLUDES = {'config.template.json', 'plants.json', 'ui_labels.json', 'button_aliases.json'}
_REGISTRY_SUBKEY = rf'Software\{APP_DIR_NAME}'
_REGISTRY_VALUE_USER_APP_DIR = 'user_app_dir'
_REGISTRY_VALUE_USER_APP_DIR_UPDATED_AT = 'user_app_dir_updated_at'
_REGISTRY_VALUE_PENDING_CLEANUP_SOURCE_DIR = 'pending_cleanup_source_dir'
_DATA_MIGRATION_ENTRIES: tuple[str, ...] = (
    PROFILES_META_FILENAME,
    INSTANCES_DIR_NAME,
    'configs',
    'models',
    'logs',
    APP_SETTINGS_FILENAME,
)


def _resolve_path(path: str | Path) -> Path:
    """将路径规范化为绝对路径。"""
    candidate = Path(path).expanduser()
    try:
        return candidate.resolve()
    except Exception:
        return candidate.absolute()


def _path_key(path: Path) -> str:
    text = str(path)
    return text.casefold()


def _is_same_path(left: Path, right: Path) -> bool:
    """判断两个路径是否指向同一位置。"""
    return _path_key(_resolve_path(left)) == _path_key(_resolve_path(right))


def _is_sub_path(path: Path, parent: Path) -> bool:
    """判断 path 是否位于 parent 内部（含同一路径）。"""
    resolved_path = _resolve_path(path)
    resolved_parent = _resolve_path(parent)
    if _is_same_path(resolved_path, resolved_parent):
        return True

    path_parts = list(resolved_path.parts)
    parent_parts = list(resolved_parent.parts)
    path_parts = [part.casefold() for part in path_parts]
    parent_parts = [part.casefold() for part in parent_parts]
    if len(path_parts) < len(parent_parts):
        return False
    return path_parts[: len(parent_parts)] == parent_parts


@dataclass(frozen=True)
class DataMigrationResult:
    """数据目录迁移结果。"""

    source_dir: Path
    target_dir: Path
    copied_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    failed_items: tuple[str, ...] = ()
    message: str = ''

    @property
    def changed(self) -> bool:
        """是否存在有效文件迁移。"""
        return self.copied_files > 0


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


def is_dev_runtime_enabled() -> bool:
    """是否启用开发态运行目录（仅源码调试场景）。"""
    if getattr(sys, 'frozen', False):
        return False

    raw = str(os.getenv('QFARM_DEV') or '').strip().lower()
    if raw == 'true':
        return True
    if raw == 'false':
        return False

    return bool(str(os.getenv('DEBUGPY_LAUNCHER_PORT') or '').strip())


def _default_user_app_dir() -> Path:
    """返回默认用户数据目录（不读取覆盖配置）。"""
    if is_dev_runtime_enabled():
        # 开发/调试态目录与发行版隔离，避免 profiles/instances 相互污染。
        return bundled_root_dir() / '.dev_appdata' / APP_DIR_NAME

    base = os.getenv('APPDATA') or os.getenv('LOCALAPPDATA')
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / 'AppData' / 'Roaming' / APP_DIR_NAME


def _read_user_app_dir_override() -> Path | None:
    """读取覆盖后的数据目录。"""
    registry_raw = read_current_user_string(_REGISTRY_SUBKEY, _REGISTRY_VALUE_USER_APP_DIR)
    if registry_raw:
        return _resolve_path(registry_raw)
    return None


def _resolve_runtime_user_app_dir() -> Path:
    """解析当前进程生效的数据目录（启动时固定）。"""
    override = _read_user_app_dir_override()
    if override is not None:
        return override
    return _resolve_path(_default_user_app_dir())


_RUNTIME_USER_APP_DIR = _resolve_runtime_user_app_dir()


def user_app_dir() -> Path:
    """返回当前进程生效的数据目录（重启后才会读取新的覆盖配置）。"""
    return _RUNTIME_USER_APP_DIR


def set_user_app_dir_override(path: str | Path) -> Path:
    """设置下次启动生效的数据目录（写入注册表）。"""
    target = _resolve_path(path)
    updated_at = datetime.now().isoformat(timespec='seconds')
    if not write_current_user_string(_REGISTRY_SUBKEY, _REGISTRY_VALUE_USER_APP_DIR, str(target)):
        raise RuntimeError('写入数据目录注册表失败。')
    write_current_user_string(_REGISTRY_SUBKEY, _REGISTRY_VALUE_USER_APP_DIR_UPDATED_AT, updated_at)
    return target


def get_pending_cleanup_source_dir() -> Path | None:
    """读取待清理旧数据目录。"""
    raw = read_current_user_string(_REGISTRY_SUBKEY, _REGISTRY_VALUE_PENDING_CLEANUP_SOURCE_DIR)
    if not raw:
        return None
    return _resolve_path(raw)


def set_pending_cleanup_source_dir(path: str | Path) -> Path:
    """记录待清理旧数据目录。"""
    target = _resolve_path(path)
    if not write_current_user_string(_REGISTRY_SUBKEY, _REGISTRY_VALUE_PENDING_CLEANUP_SOURCE_DIR, str(target)):
        raise RuntimeError('写入待清理旧目录失败。')
    return target


def clear_pending_cleanup_source_dir() -> None:
    """清空待清理旧数据目录记录。"""
    write_current_user_string(_REGISTRY_SUBKEY, _REGISTRY_VALUE_PENDING_CLEANUP_SOURCE_DIR, '')


def profiles_meta_file() -> Path:
    """返回实例元数据文件路径。"""
    return user_app_dir() / PROFILES_META_FILENAME


def user_instances_dir() -> Path:
    """返回实例根目录。"""
    return user_app_dir() / INSTANCES_DIR_NAME


def instance_dir(instance_id: str) -> Path:
    """返回实例目录。"""
    name = str(instance_id or '').strip()
    if not name:
        name = 'default'
    return user_instances_dir() / name


def instance_configs_dir(instance_id: str) -> Path:
    """返回实例 configs 目录。"""
    return instance_dir(instance_id) / 'configs'


def instance_config_file(instance_id: str) -> Path:
    """返回实例 config.json 路径。"""
    return instance_configs_dir(instance_id) / 'config.json'


def instance_logs_dir(instance_id: str) -> Path:
    """返回实例 logs 目录。"""
    return instance_dir(instance_id) / 'logs'


def instance_screenshots_dir(instance_id: str) -> Path:
    """返回实例 screenshots 目录。"""
    return instance_dir(instance_id) / 'screenshots'


def instance_error_dir(instance_id: str) -> Path:
    """返回实例错误截图目录。"""
    return instance_logs_dir(instance_id) / 'error'


def user_configs_dir() -> Path:
    """返回用户可写 configs 目录。"""
    return user_app_dir() / 'configs'


def _has_migration_payload(path: Path) -> bool:
    """判断目录是否包含可迁移数据。"""
    for name in _DATA_MIGRATION_ENTRIES:
        if (path / name).exists():
            return True
    return False


def _copy_file(src: Path, dst: Path, *, overwrite: bool = False) -> tuple[int, int, int, list[str]]:
    """复制单个文件并返回统计结果。"""
    if dst.exists() and not overwrite:
        return 0, 1, 0, []
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1, 0, 0, []
    except Exception as exc:
        return 0, 0, 1, [f'{src} -> {dst}: {exc}']


def _copy_tree(src_dir: Path, dst_dir: Path, *, overwrite: bool = False) -> tuple[int, int, int, list[str]]:
    """递归复制目录。"""
    copied = 0
    skipped = 0
    failed = 0
    failed_items: list[str] = []

    for root, _dirs, files in os.walk(src_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(src_dir)
        current_dst = dst_dir / rel_root
        current_dst.mkdir(parents=True, exist_ok=True)
        for filename in files:
            src_file = root_path / filename
            dst_file = current_dst / filename
            c, s, f, items = _copy_file(src_file, dst_file, overwrite=overwrite)
            copied += c
            skipped += s
            failed += f
            failed_items.extend(items)
    return copied, skipped, failed, failed_items


def _copy_entry(src: Path, dst: Path, *, overwrite: bool = False) -> tuple[int, int, int, list[str]]:
    """复制文件或目录入口。"""
    if src.is_dir():
        return _copy_tree(src, dst, overwrite=overwrite)
    if src.is_file():
        return _copy_file(src, dst, overwrite=overwrite)
    return 0, 0, 0, []


def _normalize_migration_source_dir(source_dir: str | Path) -> Path:
    """归一化用户选择的迁移源目录。"""
    source = _resolve_path(source_dir)
    if source.exists() and source.is_dir() and _has_migration_payload(source):
        return source
    nested = source / APP_DIR_NAME
    if nested.exists() and nested.is_dir() and _has_migration_payload(nested):
        return nested
    return source


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


def migrate_user_data(
    source_dir: str | Path,
    *,
    target_dir: str | Path | None = None,
    overwrite: bool = True,
) -> DataMigrationResult:
    """将旧数据目录迁移到目标目录（默认当前用户目录，默认覆盖同名文件）。"""
    source = _normalize_migration_source_dir(source_dir)
    target = _resolve_path(target_dir) if target_dir else _resolve_path(user_app_dir())

    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f'迁移源目录不存在: {source}')
    if _is_same_path(source, target):
        raise ValueError('迁移源目录与目标目录相同，无需迁移。')
    if not _has_migration_payload(source):
        raise ValueError(f'未在目录中发现可迁移数据: {source}')

    target.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    failed = 0
    failed_items: list[str] = []

    for name in _DATA_MIGRATION_ENTRIES:
        src_entry = source / name
        if not src_entry.exists():
            continue
        dst_entry = target / name
        c, s, f, items = _copy_entry(src_entry, dst_entry, overwrite=overwrite)
        copied += c
        skipped += s
        failed += f
        failed_items.extend(items)

    message = f'已复制 {copied} 个文件，跳过 {skipped} 个，失败 {failed} 个。'
    return DataMigrationResult(
        source_dir=source,
        target_dir=target,
        copied_files=copied,
        skipped_files=skipped,
        failed_files=failed,
        failed_items=tuple(failed_items),
        message=message,
    )


def cleanup_migrated_source_dir(source_dir: str | Path, target_dir: str | Path) -> None:
    """迁移成功后清理旧目录。"""
    source = _resolve_path(source_dir)
    target = _resolve_path(target_dir)
    if not source.exists() or not source.is_dir():
        return
    if _is_same_path(source, target):
        return
    if _is_sub_path(target, source):
        raise ValueError(f'新目录位于旧目录内，禁止自动删除旧目录: {source}')
    shutil.rmtree(source)


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
