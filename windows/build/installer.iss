; PII Vault for Windows installer (Inno Setup 6).
; Installs for the current user only (no admin prompt) into %LOCALAPPDATA%\Programs\PII Vault,
; adds Start menu and desktop shortcuts, makes sure Microsoft Edge WebView2 is present, and opens
; PII Vault when it's done. Updates run this same installer silently; the app reopens by itself.
; Your PII Vault folder, settings, vault and jobs live outside the install folder and are never touched.
;
; Build:  iscc /DAppVersion=0.4.0 windows\build\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{4AABA1FB-474F-4B55-853E-B3C2D2E50256}
AppName=PII Vault
AppVersion={#AppVersion}
AppVerName=PII Vault {#AppVersion}
AppPublisher=Data Science for Student Success, University of Mississippi
AppPublisherURL=https://github.com/stephen-dawkins/pii-vault
AppUpdatesURL=https://github.com/stephen-dawkins/pii-vault/releases
DefaultDirName={localappdata}\Programs\PII Vault
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\..\dist
OutputBaseFilename=PII-Vault-Setup
SetupIconFile=PIIVault.ico
UninstallDisplayIcon={app}\PIIVault.exe
UninstallDisplayName=PII Vault
WizardStyle=modern
WizardImageFile=wizard.bmp
WizardSmallImageFile=wizard-small.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
RestartApplications=no

[Messages]
WelcomeLabel2=This installs PII Vault {#AppVersion} on your PC.%n%nUse ChatGPT, Copilot, Gemini, Claude, or any AI tool on files with student data, without the AI ever seeing the real names. Everything runs on this PC.

[Tasks]
Name: "desktopicon"; Description: "Put a PII Vault shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\PII Vault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[InstallDelete]
; old engine files from an earlier version, so nothing stale is left behind
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\PII Vault"; Filename: "{app}\PIIVault.exe"
Name: "{userdesktop}\PII Vault"; Filename: "{app}\PIIVault.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2..."; Check: NeedsWebView2
Filename: "{app}\PIIVault.exe"; Description: "Open PII Vault"; Flags: nowait postinstall

[Code]
function NeedsWebView2: Boolean;
var
  V: String;
begin
  Result := not (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) or
                 RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) or
                 RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V));
  if not Result then
    Result := (V = '') or (V = '0.0.0.0');
end;
