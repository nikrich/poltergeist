# PyInstaller spec for the ghostbrain.api sidecar.
#
# Build with:
#   pyinstaller packaging/sidecar.spec \
#     --distpath desktop/resources/sidecar \
#     --workpath packaging/build \
#     --noconfirm
#
# Output: desktop/resources/sidecar/ghostbrain-api/  (--onedir layout)
# Electron-builder picks this up via `extraResources` in electron-builder.yml.

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_data_files,
    collect_dynamic_libs,
)

# Uvicorn and Starlette load protocol/loop implementations dynamically, so
# PyInstaller's static analysis misses them. Pull in the whole tree.
hiddenimports = []
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('anthropic')

# Semantic search is lazy-loaded from ghostbrain.api.repo.search, so PyInstaller
# can't see it from the entry point. Bundle it so packaged builds aren't crippled.
#
# transformers (and sentence_transformers + huggingface_hub) use _LazyModule
# loaders that probe `__file__`-relative paths at import time and fail when
# their .py sources only live inside the PYZ archive. collect_all() copies
# the source files to disk as data, dodges the lookup failure
# ("FileNotFoundError: ... transformers/models/__init__.pyc").
_tr_datas, _tr_bins, _tr_hidden = collect_all('transformers')
_st_datas, _st_bins, _st_hidden = collect_all('sentence_transformers')
_hf_datas, _hf_bins, _hf_hidden = collect_all('huggingface_hub')
hiddenimports += _tr_hidden + _st_hidden + _hf_hidden
hiddenimports += collect_submodules('tokenizers')
# Bare `'numpy'` isn't enough — NumPy 2.x loads numpy._core.* dynamically at
# import time (e.g. numpy._core._exceptions). Without the full submodule tree
# the packaged sidecar crashes on first import with
# "No module named 'numpy._core._exceptions'".
hiddenimports += collect_submodules('numpy')
# scipy has C extensions (.so/.dylib) that PyInstaller misses without an
# explicit dynamic-libs collection — symptom is "scipy install seems
# broken (extension modules cannot be imported)" on first scipy import,
# which sentence-transformers triggers when scoring.
hiddenimports += collect_submodules('scipy')
hiddenimports += collect_submodules('sklearn')

# Connector deps — pulled in conditionally by routes but worth including so the
# packaged sidecar matches dev behavior.
hiddenimports += collect_submodules('slack_sdk')
hiddenimports += ['frontmatter', 'yaml', 'markdownify', 'dotenv', 'jinja2', 'requests']
# jaraco.context (pulled in by pkg_resources at runtime hook time) imports
# backports.tarfile dynamically, which PyInstaller's analyzer misses.
hiddenimports += ['backports', 'backports.tarfile']

# Scheduler picks up runner shims and the worker/recorder modules dynamically.
# Pull each in so PyInstaller's static analyzer doesn't skip them.
hiddenimports += collect_submodules('ghostbrain.connectors')
hiddenimports += collect_submodules('ghostbrain.worker')
hiddenimports += collect_submodules('ghostbrain.recorder')
hiddenimports += collect_submodules('ghostbrain.profile')
hiddenimports += [
    'ghostbrain.scheduler',
    'ghostbrain.scheduler_jobs',
]

# Google Calendar uses google-api-python-client, which loads service modules
# lazily by name (build('calendar', 'v3', ...)).
hiddenimports += collect_submodules('googleapiclient')
hiddenimports += collect_submodules('google_auth_oauthlib')

datas = []
datas += collect_data_files('ghostbrain', include_py_files=False)
datas += collect_data_files('uvicorn')
datas += collect_data_files('anthropic')
# Data files (incl. source .py files for the lazy loaders) for the ML stack.
datas += _tr_datas + _st_datas + _hf_datas

# The ML stack ships its native binaries as .so/.dylib alongside the Python
# modules. collect_submodules only picks up .py files; collect_dynamic_libs is
# what actually copies the compiled extensions into the bundle.
binaries = []
binaries += collect_dynamic_libs('numpy')
binaries += collect_dynamic_libs('scipy')
binaries += collect_dynamic_libs('sklearn')
binaries += collect_dynamic_libs('torch')
binaries += collect_dynamic_libs('tokenizers')
# Also any native libs picked up by collect_all for the ML stack.
binaries += _tr_bins + _st_bins + _hf_bins

a = Analysis(
    ['../ghostbrain/api/__main__.py'],
    pathex=['..'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # We don't ship a UI from Python — strip the GUI stacks if they sneak in.
        'tkinter',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'matplotlib',
    ],
    # noarchive=True writes every .pyc to disk in its package layout instead
    # of compressing them into the PYZ archive. Required by transformers and
    # other libraries whose `_LazyModule` probes `__file__`-adjacent paths
    # at import time. Without this, search crashes with
    # "FileNotFoundError: ... transformers/models/__init__.pyc".
    noarchive=True,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ghostbrain-api',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ghostbrain-api',
)
