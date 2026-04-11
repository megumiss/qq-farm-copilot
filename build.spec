# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

rapidocr_datas = collect_data_files('rapidocr_onnxruntime')
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
        'keyboard',
        'core.engine.bot',
        'core.instance.manager',
        'gui.widgets.feature_panel',
        'gui.widgets.instance_sidebar',
        'gui.widgets.log_panel',
        'gui.widgets.status_panel',
        'gui.widgets.task_panel',
        'models.config',
        'utils.app_paths',
        'utils.logger',
        'PIL.Image',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
