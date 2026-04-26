"""Fluent 全局设置面板。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    HyperlinkLabel,
    MessageBox,
    OptionsConfigItem,
    OptionsSettingCard,
    OptionsValidator,
    PrimaryPushSettingCard,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    SwitchSettingCard,
)

from gui.widgets.fluent_container import TransparentCardContainer
from utils.app_paths import (
    APP_DIR_NAME,
    cleanup_migrated_source_dir,
    clear_pending_cleanup_source_dir,
    get_pending_cleanup_source_dir,
    migrate_user_data,
    set_pending_cleanup_source_dir,
    set_user_app_dir_override,
    user_app_dir,
)
from utils.logger import (
    DEFAULT_LOG_RETENTION_DAYS,
    MAX_LOG_RETENTION_DAYS,
    MIN_LOG_RETENTION_DAYS,
    normalize_log_retention_days,
    switch_log_directory,
)

PROJECT_URL = 'https://github.com/megumiss/qq-farm-copilot'
LICENSE_URL = f'{PROJECT_URL}/blob/main/LICENSE'
FREE_NOTICE_TEXT = '本项目仅供学习测试使用，自动化操作可能违反游戏服务条款，由此产生的一切后果由使用者自行承担。'
GPL_NOTICE_TEXT = '本项目基于 GPL-3.0 协议开源，使用、修改和分发时请遵守 GPL 条款并保留版权与许可声明。'


class _LocalOptionsSettingCard(OptionsSettingCard):
    """仅用于本面板的选项卡：不写 qconfig，全程本地值驱动。"""

    def __init__(self, config_item, icon, title, content=None, texts=None, parent=None):
        self._current_value = config_item.value
        super().__init__(config_item, icon, title, content, texts, parent)
        try:
            self.buttonGroup.buttonClicked.disconnect()
        except Exception:
            pass
        self.buttonGroup.buttonClicked.connect(self._on_button_clicked)
        self.setValue(config_item.value)

    def _on_button_clicked(self, button) -> None:
        value = button.property(self.configName)
        if value == self._current_value:
            return
        self._current_value = value
        self.configItem.value = value
        self.choiceLabel.setText(button.text())
        self.choiceLabel.adjustSize()
        self.optionChanged.emit(self.configItem)

    def setValue(self, value):
        self._current_value = value
        for button in self.buttonGroup.buttons():
            is_checked = button.property(self.configName) == value
            button.setChecked(is_checked)
            if is_checked:
                self.choiceLabel.setText(button.text())
                self.choiceLabel.adjustSize()

    def currentValue(self):
        return self._current_value


class _LogRetentionSettingCard(SettingCard):
    """日志保留天数设置卡。"""

    value_changed = pyqtSignal(int)

    def __init__(self, icon, title, content=None, *, minimum: int = 1, maximum: int = 365, parent=None):
        super().__init__(icon, title, content, parent)
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self.spin_box = SpinBox(self)
        self.spin_box.setRange(self._minimum, self._maximum)
        self.spin_box.setSingleStep(1)
        self.spin_box.setSuffix(' 天')
        self.spin_box.setFixedWidth(132)
        self.hBoxLayout.addWidget(self.spin_box, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.spin_box.valueChanged.connect(self._on_value_changed)

    def _on_value_changed(self, value: int) -> None:
        self.value_changed.emit(int(value))

    def set_value(self, value: int) -> None:
        normalized = normalize_log_retention_days(value, default=self._minimum)
        normalized = max(self._minimum, min(self._maximum, normalized))
        blocked = self.spin_box.blockSignals(True)
        self.spin_box.setValue(normalized)
        self.spin_box.blockSignals(blocked)

    def value(self) -> int:
        return int(self.spin_box.value())


class GlobalSettingsPanel(QWidget):
    """应用级设置（主题/窗口效果）。"""

    apply_requested = pyqtSignal(str, bool, int)
    check_update_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = True
        self._build_ui()
        self._loading = False

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        scroll.viewport().setStyleSheet('background: transparent;')
        root.addWidget(scroll, 1)

        container = TransparentCardContainer(self)
        scroll.setWidget(container)
        body = QVBoxLayout(container)
        body.setContentsMargins(10, 8, 14, 8)
        body.setSpacing(10)

        self._theme_config = OptionsConfigItem(
            'global_settings',
            'theme_mode',
            'auto',
            OptionsValidator(['auto', 'light', 'dark']),
        )
        self.settings_group = SettingCardGroup('全局设置', self)
        self.theme_card = _LocalOptionsSettingCard(
            self._theme_config,
            FluentIcon.BRUSH,
            '主题',
            '选择应用主题模式',
            texts=['跟随系统', '浅色', '深色'],
            parent=self.settings_group,
        )
        self.mica_card = SwitchSettingCard(
            FluentIcon.TRANSPARENT,
            '云母效果',
            '开启后使用窗口材质效果',
            parent=self.settings_group,
        )
        self.log_retention_card = _LogRetentionSettingCard(
            FluentIcon.DOCUMENT,
            '日志保留时间',
            '按天保留，超过时会自动清理 .log 文件',
            minimum=MIN_LOG_RETENTION_DAYS,
            maximum=MAX_LOG_RETENTION_DAYS,
            parent=self.settings_group,
        )
        self.settings_group.addSettingCards([self.theme_card, self.mica_card, self.log_retention_card])
        self.theme_card.optionChanged.connect(lambda *_: self._emit_apply())
        self.mica_card.checkedChanged.connect(lambda *_: self._emit_apply())
        self.log_retention_card.value_changed.connect(lambda *_: self._emit_apply())
        self.settings_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(self.settings_group)

        self.data_group = SettingCardGroup('数据目录', self)
        self.data_path_card = SettingCard(
            FluentIcon.SAVE,
            '当前数据目录',
            str(user_app_dir().resolve()),
            parent=self.data_group,
        )
        self.data_migrate_card = PrimaryPushSettingCard(
            '选择目录',
            FluentIcon.EDIT,
            '迁移数据目录',
            '将当前数据复制到新目录',
            parent=self.data_group,
        )
        self.data_cleanup_card = PrimaryPushSettingCard(
            '立即清理',
            FluentIcon.DELETE,
            '清理旧数据目录',
            '删除上次迁移前的数据目录',
            parent=self.data_group,
        )
        self.data_migrate_card.clicked.connect(self._on_pick_and_migrate_data_dir)
        self.data_cleanup_card.clicked.connect(self._on_cleanup_old_data_dir)
        self.data_group.addSettingCards([self.data_path_card, self.data_migrate_card, self.data_cleanup_card])
        self.data_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(self.data_group)

        self.version_group = SettingCardGroup('版本更新', self)
        self.version_card = SettingCard(
            FluentIcon.INFO,
            '当前版本',
            '-',
            parent=self.version_group,
        )
        self.update_card = PrimaryPushSettingCard(
            '立即检查',
            FluentIcon.SYNC,
            '检查更新',
            '从 GitHub Release 获取最新版本',
            parent=self.version_group,
        )
        self.update_card.clicked.connect(self.check_update_requested.emit)
        self.version_group.addSettingCards([self.version_card, self.update_card])
        self.version_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(self.version_group)

        body.addStretch(1)
        footer = QWidget(self)
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 10, 0, 2)
        footer_layout.setSpacing(6)

        divider = QFrame(footer)
        divider.setFixedHeight(1)
        divider.setStyleSheet('border: none; background-color: rgba(100, 116, 139, 0.24);')
        footer_layout.addWidget(divider)

        link_row = QWidget(footer)
        link_layout = QHBoxLayout(link_row)
        link_layout.setContentsMargins(0, 0, 0, 0)
        link_layout.setSpacing(10)
        link_layout.addStretch(1)

        self.project_link = HyperlinkLabel(link_row)
        self.project_link.setText('项目地址')
        self.project_link.setUrl(PROJECT_URL)
        link_layout.addWidget(self.project_link, 0, Qt.AlignmentFlag.AlignCenter)

        self.gpl_link = HyperlinkLabel(link_row)
        self.gpl_link.setText('GPL-3.0 协议')
        self.gpl_link.setUrl(LICENSE_URL)
        link_layout.addWidget(self.gpl_link, 0, Qt.AlignmentFlag.AlignCenter)
        link_layout.addStretch(1)
        footer_layout.addWidget(link_row)

        self.free_notice_label = QLabel(FREE_NOTICE_TEXT, footer)
        self.free_notice_label.setWordWrap(False)
        self.free_notice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        line_h = self.free_notice_label.fontMetrics().lineSpacing()
        self.free_notice_label.setMinimumHeight(line_h + 8)
        self.free_notice_label.setStyleSheet('color: #dc2626; font-weight: 700; padding: 2px 0;')
        footer_layout.addWidget(self.free_notice_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.gpl_notice_label = QLabel(GPL_NOTICE_TEXT, footer)
        self.gpl_notice_label.setWordWrap(False)
        self.gpl_notice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gpl_notice_label.setMinimumHeight(line_h + 8)
        self.gpl_notice_label.setStyleSheet('color: #64748b; padding: 2px 0;')
        footer_layout.addWidget(self.gpl_notice_label, 0, Qt.AlignmentFlag.AlignHCenter)

        body.addWidget(footer, 0)

    def _emit_apply(self) -> None:
        if self._loading:
            return
        self.apply_requested.emit(
            str(self.theme_card.currentValue() or 'auto'),
            bool(self.mica_card.isChecked()),
            int(self.log_retention_card.value()),
        )

    def set_values(
        self, theme_mode: str, mica_enabled: bool, log_retention_days: int = DEFAULT_LOG_RETENTION_DAYS
    ) -> None:
        self._loading = True
        value = str(theme_mode or 'auto')
        if value not in {'auto', 'light', 'dark'}:
            value = 'auto'
        self.theme_card.setValue(value)
        self.mica_card.setChecked(bool(mica_enabled))
        self.log_retention_card.set_value(normalize_log_retention_days(log_retention_days))
        self._loading = False

    def set_version_text(self, current_version: str, detail: str = '') -> None:
        version = str(current_version or '').strip() or '-'
        detail_text = str(detail or '').strip()
        content = f'v{version}' if not detail_text else f'v{version}（{detail_text}）'
        self.version_card.setContent(content)

    def _show_single_action_dialog(self, title: str, content: str) -> None:
        box = MessageBox(title, content, self)
        box.yesButton.setText('确定')
        box.cancelButton.hide()
        box.exec()

    def _restart_app_now(self) -> None:
        exe = str(sys.executable)
        if not exe:
            raise RuntimeError('无法获取可执行文件路径。')
        if getattr(sys, 'frozen', False):
            cmd = [exe]
        else:
            script = str(Path(sys.argv[0]).resolve())
            cmd = [exe, script]
        args = [str(arg) for arg in sys.argv[1:]]
        cmd.extend(args)
        subprocess.Popen(
            cmd,
            cwd=str(Path.cwd()),
            close_fds=True,
            creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
        )
        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            os._exit(0)

    def _show_restart_dialog(self, title: str, content: str) -> bool:
        box = MessageBox(title, content, self)
        box.yesButton.setText('立即重启')
        box.cancelButton.setText('稍后')
        return bool(box.exec())

    def _on_pick_and_migrate_data_dir(self) -> None:
        current_dir = Path(user_app_dir()).resolve()
        selected_dir = QFileDialog.getExistingDirectory(self, '选择新数据目录', str(current_dir.parent))
        if not selected_dir:
            return

        target_dir = Path(selected_dir).expanduser()
        try:
            target_dir = target_dir.resolve()
        except Exception:
            target_dir = target_dir.absolute()
        if target_dir.name.casefold() != APP_DIR_NAME.casefold():
            target_dir = target_dir / APP_DIR_NAME

        try:
            result = migrate_user_data(current_dir, target_dir=target_dir, overwrite=True)
        except Exception as exc:
            self._show_single_action_dialog('迁移失败', str(exc))
            return

        summary = (
            f'当前目录: {result.source_dir}\n'
            f'新目录: {result.target_dir}\n'
            f'复制文件: {result.copied_files}\n'
            f'跳过文件: {result.skipped_files}\n'
            f'失败文件: {result.failed_files}'
        )
        if result.failed_files > 0:
            details = '\n'.join(result.failed_items[:5])
            if result.failed_files > 5:
                details += f'\n... 其余 {result.failed_files - 5} 项失败请查看目录权限或占用情况。'
            self._show_single_action_dialog(
                '迁移完成（部分失败）',
                f'{summary}\n\n失败明细（最多显示 5 条）:\n{details}\n\n未切换数据目录，请修复失败项后重试。',
            )
            return

        try:
            set_user_app_dir_override(result.target_dir)
        except Exception as exc:
            self._show_single_action_dialog('迁移成功但切换失败', f'{summary}\n\n写入重启配置失败：{exc}')
            return

        if result.changed:
            try:
                switch_log_directory(
                    str((result.target_dir / 'logs').resolve()),
                    retention_days=self.log_retention_card.value(),
                )
            except Exception:
                # 日志切换失败不阻断目录切换与重启。
                pass

            try:
                set_pending_cleanup_source_dir(result.source_dir)
            except Exception as exc:
                self._show_single_action_dialog(
                    '迁移成功（清理任务记录失败）',
                    f'{summary}\n\n已设置为新数据目录，重启后生效。\n记录旧目录失败：{exc}',
                )
                return

            if self._show_restart_dialog(
                '迁移成功',
                f'{summary}\n\n已设置为新数据目录。\n旧目录待手动清理。\n\n立即重启以生效？',
            ):
                try:
                    self._restart_app_now()
                except Exception as exc:
                    self._show_single_action_dialog('重启失败', f'自动重启失败：{exc}\n请手动重启程序。')
            return

        if self._show_restart_dialog(
            '无需迁移',
            f'{summary}\n\n已设置为新数据目录。\n\n立即重启以生效？',
        ):
            try:
                self._restart_app_now()
            except Exception as exc:
                self._show_single_action_dialog('重启失败', f'自动重启失败：{exc}\n请手动重启程序。')

    def _on_cleanup_old_data_dir(self) -> None:
        source_dir = get_pending_cleanup_source_dir()
        if source_dir is None:
            self._show_single_action_dialog('无需清理', '未记录待清理的旧数据目录。')
            return

        current_dir = Path(user_app_dir()).resolve()
        try:
            cleanup_migrated_source_dir(source_dir, current_dir)
        except Exception as exc:
            self._show_single_action_dialog('清理失败', f'旧目录清理失败：{exc}')
            return

        clear_pending_cleanup_source_dir()
        self._show_single_action_dialog(
            '清理完成',
            f'已删除旧数据目录：\n{source_dir}',
        )
