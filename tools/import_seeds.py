"""从开源项目导入种子图片作为模板"""

import json
import os
import re
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

# 源目录
SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'qq-farm-bot-ui',
    'core',
    'src',
    'gameConfig',
    'seed_images_named',
)

# 目标目录
DST_DIR = ROOT / 'templates' / 'qq' / 'seed'


def _load_seed_id_by_crop_no() -> dict[str, str]:
    plants_path = ROOT / 'configs' / 'plants.json'
    data = json.loads(plants_path.read_text(encoding='utf-8'))
    out: dict[str, str] = {}
    for item in data:
        seed_id = item.get('seed_id')
        if seed_id is None:
            continue
        try:
            crop_no = int(item.get('id')) % 10000
            seed_id_int = int(seed_id)
        except (TypeError, ValueError):
            continue
        out[str(crop_no)] = str(seed_id_int)
    return out


def main():
    """程序主入口。"""
    if not os.path.exists(SRC_DIR):
        print(f'源目录不存在: {SRC_DIR}')
        return

    os.makedirs(DST_DIR, exist_ok=True)
    seed_id_by_crop_no = _load_seed_id_by_crop_no()

    count = 0
    for filename in sorted(os.listdir(SRC_DIR)):
        if not filename.endswith('.png'):
            continue

        # 跳过变异作物和狗粮
        if 'Mutant' in filename or 'dog_food' in filename:
            continue

        # 解析文件名: 20002_白萝卜_Crop_2_Seed.png → seed_20002.png
        # 或: Crop_101_Seed.png → seed_20101.png
        match = re.match(r'(\d+)_(.+?)_Crop_\d+_Seed', filename)
        if match:
            seed_id = match.group(1)
            dst_name = f'seed_{seed_id}.png'
        else:
            match2 = re.match(r'Crop_(\d+)_Seed', filename)
            if match2:
                crop_id = match2.group(1)
                seed_id = seed_id_by_crop_no.get(crop_id)
                if seed_id is None:
                    continue
                dst_name = f'seed_{seed_id}.png'
            else:
                continue

        src_path = os.path.join(SRC_DIR, filename)
        dst_path = os.path.join(DST_DIR, dst_name)

        # 复制并转换为RGBA（保留透明通道用于mask匹配）
        try:
            img = Image.open(src_path).convert('RGBA')
            img.save(dst_path)
            count += 1
            print(f'  ✓ {filename} → {dst_name} ({img.size[0]}x{img.size[1]})')
        except Exception as e:
            print(f'  ✗ {filename}: {e}')

    print(f'\n导入完成，共 {count} 个种子模板 → {DST_DIR}')


if __name__ == '__main__':
    main()
