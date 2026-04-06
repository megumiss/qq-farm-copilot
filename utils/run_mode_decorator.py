"""通用配置分发装饰器（参考 Config.when 风格）。"""

from __future__ import annotations

from functools import wraps
from typing import Any

from loguru import logger

UNSET = object()


class Config:
    """按配置条件分发同名方法。"""

    _func_list: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def when(cls, **kwargs):
        """按条件注册实现并在调用时路由到匹配实现。"""
        options = kwargs

        def decorate(func):
            name = f'{func.__module__}.{func.__qualname__}'
            data = {'options': options, 'func': func}

            if name not in cls._func_list:
                cls._func_list[name] = [data]
            else:
                override = False
                for record in cls._func_list[name]:
                    if record['options'] == data['options']:
                        record['func'] = data['func']
                        override = True
                        break
                if not override:
                    cls._func_list[name].append(data)

            @wraps(func)
            def wrapper(self, *args, **kwargs):
                records = cls._func_list.get(name, [])
                for record in records:
                    flags = [
                        _match_expected(
                            _resolve_option(self, key),
                            expected,
                        )
                        for key, expected in record['options'].items()
                    ]
                    if all(flags):
                        return record['func'](self, *args, **kwargs)

                logger.warning(f'No option fits for {name}, using last defined func.')
                return func(self, *args, **kwargs)

            return wrapper

        return decorate


def _match_expected(actual: Any, expected: Any) -> bool:
    if actual is UNSET:
        return False
    if expected is None:
        return True
    if isinstance(expected, (list, tuple, set, frozenset)):
        return actual in expected
    return actual == expected


def _resolve_option(instance: Any, key: str) -> Any:
    # 1) 自定义解析器
    resolver = getattr(instance, 'resolve_dispatch_option', None)
    if callable(resolver):
        value = resolver(key)
        if value is not UNSET:
            return value

    # 2) 实例属性
    for k in (key, key.lower()):
        if hasattr(instance, k):
            return getattr(instance, k)

    # 3) 从 config 及其常见子节点读取
    cfg = getattr(instance, 'config', None)
    if cfg is None:
        return UNSET

    for k in (key, key.lower()):
        if hasattr(cfg, k):
            return getattr(cfg, k)

    for child_name in ('safety', 'features', 'planting', 'schedule', 'sell'):
        child = getattr(cfg, child_name, None)
        if child is None:
            continue
        for k in (key, key.lower()):
            if hasattr(child, k):
                return getattr(child, k)

    return UNSET

