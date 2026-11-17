# PII Vault for Windows

The Windows version of PII Vault. Same engine, same screens, same folder layout as the Mac app.

| | Mac | Windows |
|---|---|---|
| Window | SwiftUI | HTML in Microsoft Edge WebView2 (pywebview), `windows/ui` |
| Engine | `engine/piivault` | the same engine |
| Folder | `~/PII Vault` | `C:\Users\<name>\PII Vault` (kept out of OneDrive-synced Documents and Desktop) |
| Vault and jobs | `~/Library/Application Support/PII Vault` | `%LOCALAPPDATA%\PII Vault` |
| Vault key | macOS Keychain | Windows Credential Manager |
| Scanned PDFs | Apple Vision OCR | Windows OCR (built into Windows 10/11) |
| Word to PDF | Word (AppleScript) or LibreOffice | Word (COM) or LibreOffice |
| HTML to PDF | WebKit | Microsoft Edge, headless |
| Copy Files | Finder pasteboard | File Explorer clipboard (CF_HDROP), paste with Ctrl+V |
| Install | drag to Applications | `PII-Vault-Setup.exe`, per user, no admin needed |
| Updates | GitHub Releases (`PII-Vault.zip`) | the same releases (`PII-Vault-Setup.exe` + `.sha256`) |

Needs Windows 10 (1809 or later) or Windows 11, 64-bit, 8 GB of memory.

## How it's built

`.github/workflows/windows.yml` builds on a Windows machine at GitHub:
PyInstaller makes `PIIVault.exe` (the window) and `piivault-engine.exe` (the engine), then Inno Setup
wraps them in `PII-Vault-Setup.exe`. Publishing a release attaches the installer to it automatically.
Pushes to the `windows` branch build a test installer under the run's Artifacts.

## Run from source (on Windows)

    py -3.12 -m pip install -r windows/requirements-windows.txt
    cd windows
    py -3.12 -m piivault_win

## First launch

The installer isn't signed, so Windows SmartScreen may say "Windows protected your PC".
Click **More info**, then **Run anyway**. You only do this once.
