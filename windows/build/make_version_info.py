"""Write version_info.txt (Windows file properties) from the engine's version number."""
import re, sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
v = re.search(r'__version__\s*=\s*"([^"]+)"', (root / "engine/piivault/__init__.py").read_text()).group(1)
n = tuple(int(x) for x in (v.split(".") + ["0", "0", "0"])[:4])
Path(__file__).with_name("version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={n}, prodvers={n}),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'University of Mississippi, Data Science for Student Success'),
    StringStruct('FileDescription', 'PII Vault'),
    StringStruct('FileVersion', '{v}'),
    StringStruct('ProductName', 'PII Vault'),
    StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")
print(v)
