"""模板资源路径工具：用于平台模板扫描与平台名规范化。"""

from __future__ import annotations

from pathlib import Path

DEFAULT_TEMPLATE_PLATFORM = 'qq'
VALID_TEMPLATE_PLATFORMS = {'qq', 'wechat'}


def normalize_template_platform(platform: str | None) -> str:
    """规范化平台名称；不合法值统一回退为 `qq`。"""
    text = str(platform or '').strip().lower()
    if text in VALID_TEMPLATE_PLATFORMS:
        return text
    return DEFAULT_TEMPLATE_PLATFORM


def project_root() -> Path:
    """返回项目根目录。"""
    return Path(__file__).resolve().parents[1]


def template_root(base_dir: str = 'templates') -> Path:
    """返回模板根目录（支持传入绝对路径覆盖）。"""
    base = Path(base_dir)
    if base.is_absolute():
        return base
    return (project_root() / base).resolve()


def template_scan_roots(
    platform: str | None,
    base_dir: str = 'templates',
) -> list[tuple[Path, bool]]:
    """返回模板扫描目录列表（低优先级在前，高优先级在后）。"""
    root = template_root(base_dir)
    roots: list[tuple[Path, bool]] = [(root, True)]  # legacy 根目录，需忽略平台子目录
    selected = normalize_template_platform(platform)
    roots.append((root / DEFAULT_TEMPLATE_PLATFORM, False))
    if selected != DEFAULT_TEMPLATE_PLATFORM:
        roots.append((root / selected, False))
    return roots
