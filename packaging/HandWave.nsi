Unicode True
RequestExecutionLevel user
SetCompressor /SOLID lzma

!include "MUI2.nsh"

!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "1.1.0"
!endif

!define PRODUCT_NAME "HandWave"
!define PRODUCT_PUBLISHER "HandWave"
!define PRODUCT_EXE "HandWave.exe"
!define PRODUCT_DIR_REGKEY "Software\HandWave"
!define UNINSTALL_REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\HandWave"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\dist\HandWave-${PRODUCT_VERSION}-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\HandWave"
InstallDirRegKey HKCU "${PRODUCT_DIR_REGKEY}" "InstallLocation"
Icon "..\handwave\assets\handwave.ico"
UninstallIcon "..\handwave\assets\handwave.ico"
BrandingText "HandWave"
ShowInstDetails show
ShowUninstDetails show

!define MUI_ABORTWARNING
!define MUI_ICON "..\handwave\assets\handwave.ico"
!define MUI_UNICON "..\handwave\assets\handwave.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch HandWave"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Section "HandWave" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /oname=${PRODUCT_EXE} "..\dist\HandWave.exe"
  File "..\LICENSE"
  File "..\build\THIRD_PARTY_LICENSES.txt"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\HandWave"
  CreateShortcut "$SMPROGRAMS\HandWave\HandWave.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
  CreateShortcut "$SMPROGRAMS\HandWave\Uninstall HandWave.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\HandWave.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0

  WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_REGKEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${UNINSTALL_REGKEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_REGKEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_REGKEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_EXE}"
  WriteRegStr HKCU "${UNINSTALL_REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_REGKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_REGKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTALL_REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_REGKEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\HandWave.lnk"
  Delete "$SMPROGRAMS\HandWave\HandWave.lnk"
  Delete "$SMPROGRAMS\HandWave\Uninstall HandWave.lnk"
  RMDir "$SMPROGRAMS\HandWave"

  Delete "$INSTDIR\${PRODUCT_EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD_PARTY_LICENSES.txt"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "${UNINSTALL_REGKEY}"
  DeleteRegKey HKCU "${PRODUCT_DIR_REGKEY}"
SectionEnd
