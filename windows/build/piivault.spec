# PyInstaller build: two programs that share one folder.
#   PIIVault.exe          the window (no console)
#   piivault-engine.exe   the engine the window runs for each job (console program, started hidden)
# Build from the repo root:  pyinstaller --noconfirm windows/build/piivault.spec
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ENGINE = os.path.join(ROOT, "engine")
WIN = os.path.join(ROOT, "windows")
ICON = os.path.join(SPECPATH, "PIIVault.ico")

hidden = (collect_submodules("piivault") + collect_submodules("winrt") + collect_submodules("webview")
          + ["keyring.backends.Windows", "win32timezone", "win32com.client", "pythoncom", "pywintypes"])
datas = [(os.path.join(WIN, "ui"), "ui")] + collect_data_files("webview") + collect_data_files("docx") + collect_data_files("pptx")
binaries = collect_dynamic_libs("winrt") + collect_dynamic_libs("pymupdf")
excludes = ["tkinter", "matplotlib", "pandas", "numpy.tests", "IPython", "spacy", "torch"]

a_gui = Analysis([os.path.join(SPECPATH, "launch_gui.py")], pathex=[WIN, ENGINE], datas=datas, binaries=binaries,
                 hiddenimports=hidden, excludes=excludes)
a_eng = Analysis([os.path.join(SPECPATH, "launch_engine.py")], pathex=[ENGINE], datas=[], binaries=binaries,
                 hiddenimports=hidden, excludes=excludes)

pyz_gui = PYZ(a_gui.pure)
pyz_eng = PYZ(a_eng.pure)
exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="PIIVault", icon=ICON, console=False,
              version=os.path.join(SPECPATH, "version_info.txt"))
exe_eng = EXE(pyz_eng, a_eng.scripts, [], exclude_binaries=True, name="piivault-engine", icon=ICON, console=True,
              version=os.path.join(SPECPATH, "version_info.txt"))
coll = COLLECT(exe_gui, a_gui.binaries, a_gui.datas, exe_eng, a_eng.binaries, a_eng.datas,
               name="PII Vault", upx=False)
