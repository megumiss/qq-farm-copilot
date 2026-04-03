"""图像处理工具"""

from PIL import Image


def save_screenshot(image: Image.Image, path: str):
    """保存截图"""
    image.save(path, format='PNG')
