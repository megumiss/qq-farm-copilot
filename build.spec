# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

rapidocr_datas = collect_data_files('rapidocr')
core_gui_binary = [('gui/main_window_core.pyd', 'gui')]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=core_gui_binary,
    datas=[
        ('configs', 'configs'),
        ('templates', 'templates'),
        ('gui/icons', 'gui/icons'),
    ]
    + rapidocr_datas,
    hiddenimports=[
        'PyQt6.sip',
        'qfluentwidgets',
        'keyboard',
        'core.engine.bot',
        'core.update_checker',
        'core.instance.manager',
        'gui.dialog_styles',
        'gui.window_loader',
        'gui.main_window_core',
        'gui.steal_chart_panel',
        'gui.widgets',
        'models.config',
        'utils.app_paths',
        'utils.logger',
        'utils.version',
        'PIL.Image',
        'gui.widgets.feature_panel',
        'gui.widgets.global_settings_panel',
        'gui.widgets.instance_manage_panel',
        'gui.widgets.instance_sidebar',
        'gui.widgets.land_detail_panel',
        'gui.widgets.log_panel',
        'gui.widgets.settings_panel',
        'gui.widgets.status_panel',
        'gui.widgets.task_panel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['tools/pyi_rth_preload_onnxruntime.py'],
    excludes=['easyocr', 'torch', 'torchvision', 'torchaudio'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='QQFarmCopilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='gui/icons/app_icon.ico',
)
