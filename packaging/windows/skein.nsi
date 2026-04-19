; Skein NSIS installer script
;
; Build with:  makensis packaging/windows/skein.nsi
; Requires:    NSIS 3.x and a prior `pyinstaller packaging/windows/skein.spec`
;              that produced dist\skein\

!define APP_NAME       "Skein"
!define APP_VERSION    "0.1.0"
!define APP_PUBLISHER  "Jonny Armstrong"
!define APP_URL        "https://github.com/jarmstrong158/skein"
!define APP_EXE        "skein.exe"
!define INSTDIR_REG    "Software\${APP_NAME}"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "..\..\dist\Skein-${APP_VERSION}-Setup.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${INSTDIR_REG}" "Install_Dir"
RequestExecutionLevel admin

!include "MUI2.nsh"

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Skein (required)" SecMain
    SectionIn RO
    SetOutPath "$INSTDIR"
    File /r "..\..\dist\skein\*.*"

    ; Default config
    SetOutPath "$INSTDIR\data"
    File /oname=config.example.json "..\..\config.example.json"

    ; Registry / Add-Remove
    WriteRegStr HKLM "${INSTDIR_REG}" "Install_Dir" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "URLInfoAbout" "${APP_URL}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1

    WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Start Menu shortcuts" SecShortcuts
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Skein (serve).lnk" "$INSTDIR\${APP_EXE}" "serve"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Skein dashboard.lnk" "http://127.0.0.1:5050"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\${APP_NAME}\*.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKLM "${INSTDIR_REG}"
SectionEnd
