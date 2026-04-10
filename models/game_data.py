"""游戏数据 - 作物信息、等级经验等静态数据"""

from __future__ import annotations

from utils.app_paths import load_config_json_array


def _parse_grow_phases_seconds(grow_phases: str) -> list[int]:
    """Parse `种子:30;发芽:30;成熟:0;` into [30, 30, 0]."""
    phases: list[int] = []
    for part in (grow_phases or '').split(';'):
        part = part.strip()
        if not part or ':' not in part:
            continue
        _, sec_str = part.split(':', 1)
        sec_str = sec_str.strip()
        try:
            sec = int(float(sec_str))
        except ValueError:
            continue
        if sec < 0:
            continue
        phases.append(sec)
    return phases


def _calc_grow_time_seconds(grow_phases: str, seasons: int) -> int:
    """Compute total grow time.

    Rules:
    1. Base grow time = sum of all phase seconds.
    2. For dual-season crops (`seasons == 2`), add the last two non-zero phases.
    """
    phases = _parse_grow_phases_seconds(grow_phases)
    total = sum(phases)

    if seasons == 2:
        non_zero = [s for s in phases if s > 0]
        if len(non_zero) >= 2:
            total += non_zero[-1] + non_zero[-2]
        elif len(non_zero) == 1:
            total += non_zero[-1]
    return total


def _load_crops_from_plant_json() -> list[tuple]:
    """Build CROPS tuple list from `configs/plants.json`.

    Tuple format:
      (name, seed_id, land_level_need, grow_time_seconds, exp, fruit_count)
    """
    data = load_config_json_array('plants.json', prefer_user=False)

    crops: list[tuple] = []
    for item in data:
        name = str(item.get('name', '')).strip()
        if not name:
            continue

        seed_id = int(item.get('seed_id', 0))
        land_level_need = int(item.get('land_level_need', 0))
        seasons = int(item.get('seasons', 1))
        grow_phases = str(item.get('grow_phases', ''))
        grow_time = _calc_grow_time_seconds(grow_phases, seasons)

        exp = int(item.get('exp', 0))
        if seasons == 2:
            exp *= 2

        fruit = item.get('fruit', {}) or {}
        fruit_count = int(fruit.get('count', 0))

        crops.append((name, seed_id, land_level_need, grow_time, exp, fruit_count))

    crops.sort(key=lambda c: (c[2], c[1], c[0]))
    return crops


# 作物数据表：(名称, 种子ID, 解锁等级, 总生长时间秒, 经验, 果实数量)
CROPS = _load_crops_from_plant_json()


def get_crop_names() -> list[str]:
    """获取所有作物名称列表"""
    return [c[0] for c in CROPS]


def get_crops_for_level(level: int) -> list[tuple]:
    """获取指定等级可种植的作物"""
    return [c for c in CROPS if c[2] <= level]


def get_crop_by_name(name: str) -> tuple | None:
    """根据名称查找作物"""
    for c in CROPS:
        if c[0] == name:
            return c
    return None


def get_best_crop_for_level(level: int) -> tuple | None:
    """获取当前等级下单位时间经验最高的作物

    计算公式：经验 / 生长时间（秒），值越大效率越高。
    """
    available = get_crops_for_level(level)
    if not available:
        return None
    return max(available, key=lambda c: c[4] / c[3])


def get_latest_crop_for_level(level: int) -> tuple | None:
    """获取当前等级下可种植的最高等级作物。"""
    available = get_crops_for_level(level)
    if not available:
        return None
    max_level = max(c[2] for c in available)
    latest = [c for c in available if c[2] == max_level]
    return max(latest, key=lambda c: (c[1], c[0]))


def get_crop_index_in_list(name: str, level: int) -> int:
    """获取指定作物在当前等级可种列表中的位置索引（从0开始）

    游戏中点击空地后弹出的种子列表是按解锁等级排序的。
    返回该作物在列表中的位置，用于相对位置点击。
    返回 -1 表示未找到。
    """
    available = get_crops_for_level(level)
    for i, c in enumerate(available):
        if c[0] == name:
            return i
    return -1


def format_grow_time(seconds: int) -> str:
    """格式化生长时间"""
    if seconds < 60:
        return f'{seconds}秒'
    if seconds < 3600:
        return f'{seconds // 60}分钟'
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    return f'{hours}小时{mins}分' if mins else f'{hours}小时'


def get_crop_display_info() -> list[str]:
    """获取作物显示信息列表，用于下拉框"""
    items = []
    for name, _, level, grow_time, exp, _ in CROPS:
        time_str = format_grow_time(grow_time)
        items.append(f'{name} (Lv{level}, {time_str}, {exp}经验)')
    return items
