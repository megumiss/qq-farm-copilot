# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

rapidocr_datas = collect_data_files('rapidocr_onnxruntime')
gui_hiddenimports = ['gui.dialog_styles'] + collect_submodules('gui.widgets')
core_gui_binary = [('gui/main_window_core.pyd', 'gui')]
gui_package_datas = collect_data_files(
    'gui',
    include_py_files=True,
    includes=[
        '__init__.py',
        'dialog_styles.py',
        'widgets/__init__.py',
        'widgets/*.py',
    ],
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=core_gui_binary,
    datas=[
        ('configs', 'configs'),
        ('templates', 'templates'),
        ('gui/icons', 'gui/icons'),
    ]
    + gui_package_datas
    + rapidocr_datas,
    hiddenimports=[
        'PyQt6.sip',
        'keyboard',
        'core.engine.bot',
        'core.instance.manager',
        'models.config',
        'utils.app_paths',
        'utils.logger',
        'PIL.Image',
    ]
    + gui_hiddenimports,
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
