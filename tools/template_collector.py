"""模板采集工具（对齐项目窗口/截图逻辑）。

流程：
1. 调用项目的窗口分辨率调整流程，默认按 QQ 平台调到 540x960。
2. 使用项目同款截图裁剪规则（capture_rect + crop_window_image_for_preview）。
3. 鼠标框选模板区域，保存时弹出系统文件保存窗口（默认 PNG）。
4. 保存为 button 风格模板：框内保留原图，框外全部涂黑。
"""

import os
import sys
import time
from datetime import datetime
from tkinter import Tk, filedialog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from core.platform.screen_capture import ScreenCapture
from core.platform.window_manager import WindowManager

# 显示窗口的最大尺寸（适配屏幕）
MAX_DISPLAY_WIDTH = 1280
MAX_DISPLAY_HEIGHT = 800


class TemplateCollector:
    """交互式模板采集工具。"""

    def __init__(self):
        """初始化窗口管理、截图与交互状态。"""
        self.wm = WindowManager()
        self.sc = ScreenCapture()
        self.templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
        os.makedirs(self.templates_dir, exist_ok=True)
        self._drawing = False
        self._start_point = None  # 显示坐标
        self._end_point = None  # 显示坐标
        self._original_image = None  # 原始截图（全分辨率）
        self._display_image = None  # 缩放后用于显示的图
        self._scale = 1.0  # 缩放比例
        self._known_prefixes = {'btn', 'icon', 'crop', 'ui', 'land', 'seed'}
        self._toolbar_height = 44
        self._button_rects: dict[str, tuple[int, int, int, int]] = {}
        self._pending_action: str | None = None
        self._canvas_aspect_ratio: float = 1.0
        self._active_platform: str = 'qq'

    @staticmethod
    def _to_cv_bgr(image) -> np.ndarray:
        """将 PIL Image 转为 OpenCV BGR 图像。"""
        rgb = np.array(image.convert('RGB'))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def _prepare_window(self, keyword: str, platform: str = 'qq', position: str = 'left_center') -> bool:
        """查找并激活窗口，然后按项目逻辑调整分辨率。"""
        window = self.wm.find_window(keyword)
        if not window:
            print(f"未找到包含 '{keyword}' 的窗口")
            print('请先打开微信小程序中的QQ农场')
            return False

        self.wm.activate_window()
        time.sleep(0.3)
        ok = self.wm.resize_window(position=position, platform=platform)
        time.sleep(0.3)
        self.wm.refresh_window_info(keyword)

        if not ok:
            print(f'窗口尺寸调整失败（平台: {platform}），将继续尝试采集当前窗口画面')
        return True

    def _resolve_save_path(self, name: str) -> str:
        """按当前平台与模板名前缀计算默认保存路径。"""
        prefix = (name.split('_')[0] if '_' in name else name).lower()
        subdir = prefix if prefix in self._known_prefixes else 'unknown'
        save_dir = os.path.join(self.templates_dir, self._active_platform, subdir)
        os.makedirs(save_dir, exist_ok=True)
        return os.path.join(save_dir, f'{name}.png')

    def capture_game_window(self, keyword: str = 'QQ经典农场', platform: str = 'qq') -> np.ndarray | None:
        """按项目截图与裁剪逻辑采集游戏画面。"""
        if not self._prepare_window(keyword=keyword, platform=platform):
            return None

        rect = self.wm.get_capture_rect()
        if not rect:
            rect = self.wm.get_window_rect()
        if not rect:
            print('无法获取窗口截图区域')
            return None

        image = self.sc.capture_region(rect)
        if image is None:
            print('截屏失败')
            return None

        # 与主流程对齐：截图后再按 nonclient 规则裁成识别画面。
        cropped = self.wm.crop_window_image_for_preview(image, platform)
        if cropped is None:
            print('截图裁剪失败')
            return None
        return self._to_cv_bgr(cropped)

    def _resize_for_display(self, image: np.ndarray) -> np.ndarray:
        """缩放图片以适配屏幕显示，并记录缩放比例。"""
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
        """将显示坐标转换为原图坐标。"""
        ox = int(x / self._scale)
        oy = int(y / self._scale)
        # 限制在原图范围内
        h, w = self._original_image.shape[:2]
        ox = max(0, min(ox, w - 1))
        oy = max(0, min(oy, h - 1))
        return ox, oy

    def _hit_button(self, x: int, y: int) -> str | None:
        """命中顶部按钮栏时返回按钮动作名。"""
        for key, (x1, y1, x2, y2) in self._button_rects.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                return key
        return None

    def _window_to_image_point(self, x: int, y: int) -> tuple[int, int] | None:
        """将窗口坐标转换为图像区坐标（排除顶部按钮栏）。"""
        if self._display_image is None:
            return None
        h, w = self._display_image.shape[:2]
        iy = int(y - self._toolbar_height)
        ix = int(x)
        if ix < 0 or iy < 0 or ix >= w or iy >= h:
            return None
        return ix, iy

    def _window_to_image_point_clamped(self, x: int, y: int) -> tuple[int, int] | None:
        """将窗口坐标转换为图像坐标并进行边界夹紧。"""
        if self._display_image is None:
            return None
        h, w = self._display_image.shape[:2]
        ix = max(0, min(int(x), w - 1))
        iy = max(0, min(int(y - self._toolbar_height), h - 1))
        return ix, iy

    def _build_toolbar(self, width: int) -> np.ndarray:
        """绘制顶部按钮栏并更新按钮命中区域。"""
        bar = np.full((self._toolbar_height, width, 3), 242, dtype=np.uint8)
        self._button_rects.clear()
        # OpenCV 默认字体不支持中文，按钮文案使用英文避免乱码。
        spec = [('save', 'Save'), ('refresh', 'Refresh'), ('quit', 'Quit')]
        x = 10
        btn_h = 30
        btn_w = 112
        y1 = (self._toolbar_height - btn_h) // 2
        y2 = y1 + btn_h
        for key, label in spec:
            x1, x2 = x, x + btn_w
            self._button_rects[key] = (x1, y1, x2, y2)
            cv2.rectangle(bar, (x1, y1), (x2, y2), (210, 210, 210), thickness=-1)
            cv2.rectangle(bar, (x1, y1), (x2, y2), (130, 130, 130), thickness=1)
            cv2.putText(bar, label, (x1 + 14, y1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1, cv2.LINE_AA)
            x = x2 + 10
        return bar

    def _render_canvas(self) -> np.ndarray:
        """渲染当前可视画面（按钮栏 + 预览图 + 选择框）。"""
        img = self._display_image.copy()
        if self._start_point and self._end_point:
            cv2.rectangle(img, self._start_point, self._end_point, (0, 255, 0), 2)
            ox1, oy1 = self._display_to_original(*self._start_point)
            ox2, oy2 = self._display_to_original(*self._end_point)
            label = f'({ox1},{oy1})->({ox2},{oy2}) {abs(ox2 - ox1)}x{abs(oy2 - oy1)}'
            label_x = min(max(6, min(self._start_point[0], self._end_point[0]) + 6), max(6, img.shape[1] - 260))
            label_y = max(16, min(self._start_point[1], self._end_point[1]) - 6)
            cv2.putText(img, label, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)

        toolbar = self._build_toolbar(img.shape[1])
        canvas = np.vstack([toolbar, img])
        ch, cw = canvas.shape[:2]
        if ch > 0:
            self._canvas_aspect_ratio = float(cw) / float(ch)
        return canvas

    def _enforce_window_ratio(self, window_name: str):
        """强制窗口保持画布比例，避免自由拉伸导致变形。"""
        if self._canvas_aspect_ratio <= 0:
            return
        if not hasattr(cv2, 'getWindowImageRect'):
            return
        try:
            _x, _y, cur_w, cur_h = cv2.getWindowImageRect(window_name)
        except Exception:
            return
        if cur_w <= 0 or cur_h <= 0:
            return
        expected_h = int(round(cur_w / self._canvas_aspect_ratio))
        if abs(expected_h - cur_h) <= 2:
            return
        cv2.resizeWindow(window_name, int(cur_w), max(120, int(expected_h)))

    def _reset_selection(self):
        """清除当前框选状态。"""
        self._drawing = False
        self._start_point = None
        self._end_point = None

    def _mouse_callback(self, event, x, y, flags, param):
        """处理按钮点击与框选拖拽交互。"""
        if event == cv2.EVENT_LBUTTONDOWN:
            action = self._hit_button(x, y)
            if action:
                self._pending_action = action
                return
            pt = self._window_to_image_point(x, y)
            if pt is None:
                return
            self._drawing = True
            self._start_point = pt
            self._end_point = pt
        elif event == cv2.EVENT_MOUSEMOVE and self._drawing:
            pt = self._window_to_image_point_clamped(x, y)
            if pt is not None:
                self._end_point = pt
        elif event == cv2.EVENT_LBUTTONUP:
            if not self._drawing:
                return
            self._drawing = False
            pt = self._window_to_image_point_clamped(x, y)
            if pt is not None:
                self._end_point = pt

    @staticmethod
    def _build_button_style_template(image: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
        """生成 button 风格模板：框内保留，框外全黑。"""
        out = np.zeros_like(image)
        out[y1:y2, x1:x2] = image[y1:y2, x1:x2]
        return out

    def _ask_save_path(self, suggested_name: str) -> str:
        """弹出系统保存对话框，返回用户选择路径。"""
        root = Tk()
        root.withdraw()
        try:
            root.attributes('-topmost', True)
        except Exception:
            pass

        initial_path = self._resolve_save_path(suggested_name)
        initial_dir = os.path.dirname(initial_path)
        initial_file = os.path.basename(initial_path)
        path = filedialog.asksaveasfilename(
            title='保存模板',
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension='.png',
            filetypes=[('PNG 图片', '*.png'), ('所有文件', '*.*')],
        )
        root.destroy()
        return str(path or '')

    def run(self):
        """运行模板采集交互主循环。"""
        print('=' * 50)
        print('  QQ农场模板采集工具')
        print('=' * 50)
        print()
        print('操作说明：')
        print('  1. 鼠标左键拖拽框选模板区域')
        print('  2. 点击顶部“保存”按钮保存当前框选区域')
        print('  3. 点击顶部“重截”按钮重新截图')
        print('  4. 点击顶部“退出”按钮关闭工具')
        print('  5. 保存结果会自动转为 button 样式（框外全黑）')
        print()
        print('窗口调整：默认按 QQ 平台将窗口调整为 540x960（项目同款逻辑）')
        print()

        platform = 'qq'
        self._active_platform = platform
        self._original_image = self.capture_game_window(platform=platform)
        if self._original_image is None:
            return

        h, w = self._original_image.shape[:2]
        print(f'截图尺寸: {w}x{h}')

        self._display_image = self._resize_for_display(self._original_image)
        if self._scale < 1.0:
            dh, dw = self._display_image.shape[:2]
            print(f'显示缩放: {self._scale:.2f} ({dw}x{dh})')

        window_name = 'Template Collector'
        # 允许拉伸窗口，同时保持显示比例不变。
        flags = cv2.WINDOW_NORMAL
        if hasattr(cv2, 'WINDOW_KEEPRATIO'):
            flags |= cv2.WINDOW_KEEPRATIO
        cv2.namedWindow(window_name, flags)
        cv2.resizeWindow(window_name, self._display_image.shape[1], self._display_image.shape[0] + self._toolbar_height)
        if hasattr(cv2, 'WND_PROP_ASPECT_RATIO') and hasattr(cv2, 'WINDOW_KEEPRATIO'):
            try:
                cv2.setWindowProperty(window_name, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_KEEPRATIO)
            except Exception:
                pass
        cv2.setMouseCallback(window_name, self._mouse_callback)

        saved_count = 0

        while True:
            canvas = self._render_canvas()
            cv2.imshow(window_name, canvas)
            cv2.waitKey(30)
            self._enforce_window_ratio(window_name)

            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break

            action = self._pending_action
            self._pending_action = None
            if action == 'quit':
                break

            if action == 'refresh':
                print('重新截屏...')
                self._original_image = self.capture_game_window(platform=platform)
                if self._original_image is not None:
                    self._display_image = self._resize_for_display(self._original_image)
                    self._reset_selection()
                    h, w = self._original_image.shape[:2]
                    print(f'截屏完成 ({w}x{h})')
                continue

            if action == 'save':
                if self._start_point and self._end_point:
                    # 转换为原图坐标
                    ox1, oy1 = self._display_to_original(*self._start_point)
                    ox2, oy2 = self._display_to_original(*self._end_point)
                    x1, y1 = min(ox1, ox2), min(oy1, oy2)
                    x2, y2 = max(ox1, ox2), max(oy1, oy2)

                    if x2 - x1 < 5 or y2 - y1 < 5:
                        print('框选区域太小，请重新框选')
                        continue

                    styled = self._build_button_style_template(self._original_image, x1, y1, x2, y2)
                    cv2.namedWindow('Preview', cv2.WINDOW_NORMAL)
                    cv2.imshow('Preview', styled)
                    print(f'\n框选区域: ({x1},{y1})->({x2},{y2}), 大小: {x2 - x1}x{y2 - y1}')

                    default_name = f'template_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                    filepath = self._ask_save_path(default_name)
                    if not filepath:
                        print('已取消保存')
                        continue

                    if not filepath.lower().endswith('.png'):
                        filepath = f'{filepath}.png'
                    save_dir = os.path.dirname(filepath)
                    if save_dir:
                        os.makedirs(save_dir, exist_ok=True)

                    # cv2.imwrite 不支持中文路径，用 imencode + 写文件
                    success, buf = cv2.imencode('.png', styled)
                    if success:
                        buf.tofile(filepath)
                        saved_count += 1
                        print(f'✓ 已保存: {filepath} (第{saved_count}个)')
                    else:
                        print('保存失败：图像编码失败')

                    self._display_image = self._resize_for_display(self._original_image)
                    self._reset_selection()
                    cv2.destroyWindow('Preview')
                else:
                    print('请先用鼠标框选一个区域')

        cv2.destroyAllWindows()
        print(f'\n采集完成，共保存 {saved_count} 个模板到 {self.templates_dir}')


if __name__ == '__main__':
    collector = TemplateCollector()
    collector.run()
