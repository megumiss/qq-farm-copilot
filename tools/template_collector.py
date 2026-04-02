"""模板采集工具 - 从游戏截图中裁剪并保存模板图片

使用方法：
1. 打开QQ农场小程序窗口
2. 运行此脚本: python tools/template_collector.py
3. 程序会截取游戏窗口画面
4. 用鼠标框选要保存的模板区域
5. 输入模板名称（如 btn_harvest, icon_weed 等）
6. 模板自动保存到 templates/ 目录

命名规范：
  btn_xxx    - 按钮（收获、播种、浇水等）
  icon_xxx   - 状态图标（虫子、杂草、缺水等）
  crop_xxx   - 作物状态（成熟、枯死等）
  land_xxx   - 土地状态（空地等）
  ui_xxx     - UI元素（返回按钮等）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from core.window_manager import WindowManager
from core.screen_capture import ScreenCapture

# 显示窗口的最大尺寸（适配屏幕）
MAX_DISPLAY_WIDTH = 1280
MAX_DISPLAY_HEIGHT = 800


class TemplateCollector:
    def __init__(self):
        self.wm = WindowManager()
        self.sc = ScreenCapture()
        self.templates_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "templates"
        )
        os.makedirs(self.templates_dir, exist_ok=True)
        self._drawing = False
        self._start_point = None  # 显示坐标
        self._end_point = None    # 显示坐标
        self._original_image = None   # 原始截图（全分辨率）
        self._display_image = None    # 缩放后用于显示的图
        self._scale = 1.0             # 缩放比例
        self._known_prefixes = {"btn", "icon", "crop", "ui", "land", "seed"}

    def _resolve_save_path(self, name: str) -> str:
        prefix = (name.split("_")[0] if "_" in name else name).lower()
        subdir = prefix if prefix in self._known_prefixes else "unknown"
        save_dir = os.path.join(self.templates_dir, subdir)
        os.makedirs(save_dir, exist_ok=True)
        return os.path.join(save_dir, f"{name}.png")

    def capture_game_window(self, keyword: str = "QQ经典农场") -> np.ndarray | None:
        window = self.wm.find_window(keyword)
        if not window:
            print(f"未找到包含 '{keyword}' 的窗口")
            print("请先打开微信小程序中的QQ农场")
            return None

        self.wm.activate_window()
        import time
        time.sleep(0.5)

        rect = (window.left, window.top, window.width, window.height)
        image = self.sc.capture_region(rect)
        if image is None:
            print("截屏失败")
            return None

        rgb = np.array(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def _resize_for_display(self, image: np.ndarray) -> np.ndarray:
        """缩放图片以适配屏幕显示，并记录缩放比例"""
        h, w = image.shape[:2]
        scale_w = MAX_DISPLAY_WIDTH / w if w > MAX_DISPLAY_WIDTH else 1.0
        scale_h = MAX_DISPLAY_HEIGHT / h if h > MAX_DISPLAY_HEIGHT else 1.0
        self._scale = min(scale_w, scale_h)

        if self._scale < 1.0:
            new_w = int(w * self._scale)
            new_h = int(h * self._scale)
            return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            self._scale = 1.0
            return image.copy()

    def _display_to_original(self, x: int, y: int) -> tuple[int, int]:
        """将显示坐标转换为原图坐标"""
        ox = int(x / self._scale)
        oy = int(y / self._scale)
        # 限制在原图范围内
        h, w = self._original_image.shape[:2]
        ox = max(0, min(ox, w - 1))
        oy = max(0, min(oy, h - 1))
        return ox, oy

    def _mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self._drawing = True
            self._start_point = (x, y)
            self._end_point = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self._drawing:
            self._end_point = (x, y)
            # 在缩放后的图上画框
            self._display_image = self._resize_for_display(self._original_image)
            cv2.rectangle(self._display_image, self._start_point,
                          self._end_point, (0, 255, 0), 2)
            # 显示原图坐标
            ox1, oy1 = self._display_to_original(*self._start_point)
            ox2, oy2 = self._display_to_original(x, y)
            label = f"({ox1},{oy1})->({ox2},{oy2}) {abs(ox2-ox1)}x{abs(oy2-oy1)}"
            cv2.putText(self._display_image, label, (x + 10, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        elif event == cv2.EVENT_LBUTTONUP:
            self._drawing = False
            self._end_point = (x, y)

    def run(self):
        print("=" * 50)
        print("  QQ农场模板采集工具")
        print("=" * 50)
        print()
        print("操作说明：")
        print("  1. 鼠标左键拖拽框选模板区域")
        print("  2. 按 S 保存当前框选区域")
        print("  3. 按 R 重新截屏")
        print("  4. 按 Q 退出")
        print()
        print("命名规范：")
        print("  btn_harvest  - 收获按钮      icon_weed   - 杂草图标")
        print("  btn_plant    - 播种按钮      icon_bug    - 虫子图标")
        print("  btn_water    - 浇水按钮      icon_water  - 缺水图标")
        print("  btn_weed     - 除草按钮      icon_mature - 成熟标志")
        print("  btn_bug      - 除虫按钮      crop_mature - 成熟作物")
        print("  btn_close    - 关闭弹窗      crop_dead   - 枯死作物")
        print("  btn_sell     - 出售按钮      land_empty  - 空地")
        print()

        self._original_image = self.capture_game_window()
        if self._original_image is None:
            return

        h, w = self._original_image.shape[:2]
        print(f"截图尺寸: {w}x{h}")

        self._display_image = self._resize_for_display(self._original_image)
        if self._scale < 1.0:
            dh, dw = self._display_image.shape[:2]
            print(f"显示缩放: {self._scale:.2f} ({dw}x{dh})")

        window_name = "Template Collector - S:Save R:Refresh Q:Quit"
        cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(window_name, self._mouse_callback)

        saved_count = 0

        while True:
            cv2.imshow(window_name, self._display_image)
            key = cv2.waitKey(30) & 0xFF

            if key == ord('q') or key == 27:
                break

            elif key == ord('r'):
                print("重新截屏...")
                self._original_image = self.capture_game_window()
                if self._original_image is not None:
                    self._display_image = self._resize_for_display(self._original_image)
                    self._start_point = None
                    self._end_point = None
                    h, w = self._original_image.shape[:2]
                    print(f"截屏完成 ({w}x{h})")

            elif key == ord('s'):
                if self._start_point and self._end_point:
                    # 转换为原图坐标
                    ox1, oy1 = self._display_to_original(*self._start_point)
                    ox2, oy2 = self._display_to_original(*self._end_point)
                    x1, y1 = min(ox1, ox2), min(oy1, oy2)
                    x2, y2 = max(ox1, ox2), max(oy1, oy2)

                    if x2 - x1 < 5 or y2 - y1 < 5:
                        print("框选区域太小，请重新框选")
                        continue

                    cropped = self._original_image[y1:y2, x1:x2]
                    cv2.imshow("Preview", cropped)
                    print(f"\n原图裁剪: ({x1},{y1})->({x2},{y2}), 大小: {x2-x1}x{y2-y1}")

                    name = input("输入模板名称 (如 btn_harvest): ").strip()
                    if not name:
                        print("已取消")
                        continue

                    filepath = self._resolve_save_path(name)
                    # cv2.imwrite 不支持中文路径，用 imencode + 写文件
                    success, buf = cv2.imencode('.png', cropped)
                    if success:
                        buf.tofile(filepath)
                    saved_count += 1
                    print(f"✓ 已保存: {filepath} (第{saved_count}个)")

                    self._display_image = self._resize_for_display(self._original_image)
                    self._start_point = None
                    self._end_point = None
                    cv2.destroyWindow("Preview")
                else:
                    print("请先用鼠标框选一个区域")

        cv2.destroyAllWindows()
        print(f"\n采集完成，共保存 {saved_count} 个模板到 {self.templates_dir}")


if __name__ == "__main__":
    collector = TemplateCollector()
    collector.run()
