# PyInstaller spec for SchemeUp. Run it through packaging/build.ps1, from the repository root.
#
# The result is a folder, dist/SchemeUp, not a single file: a one-file build unpacks itself
# to a temporary folder on every launch, which makes the program slow to start and looks
# like malware to antivirus tools.

import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

root = Path(SPECPATH).parent
sys.path.insert(0, str(root / "src"))
from schemeup import __version__  # noqa: E402

numbers = tuple(int(part) for part in __version__.split(".")[:3])
numbers = (*numbers, 0) + (0,) * (3 - len(numbers))

# The Windows "Details" tab of the exe, which also helps antivirus tools trust it.
version_file = root / "build" / "version_info.txt"
version_file.parent.mkdir(exist_ok=True)
version_file.write_text(
    str(
        VSVersionInfo(
            ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
            kids=[
                StringFileInfo(
                    [
                        StringTable(
                            "040904B0",
                            [
                                StringStruct("CompanyName", "Xuanyi Qiu"),
                                StringStruct("FileDescription", "SchemeUp"),
                                StringStruct("FileVersion", __version__),
                                StringStruct("InternalName", "SchemeUp"),
                                StringStruct("LegalCopyright", "MIT License"),
                                StringStruct("OriginalFilename", "SchemeUp.exe"),
                                StringStruct("ProductName", "SchemeUp"),
                                StringStruct("ProductVersion", __version__),
                            ],
                        )
                    ]
                ),
                VarFileInfo([VarStruct("Translation", [1033, 1200])]),
            ],
        )
    ),
    encoding="utf-8",
)

# The app only uses these Qt modules; leaving out the rest keeps the download small.
unused_qt = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtUiTools",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtXml",
    "PySide6.QtConcurrent",
    "PySide6.QtDBus",
]

analysis = Analysis(
    [str(root / "packaging" / "launch.py")],
    pathex=[str(root / "src")],
    datas=[(str(root / "src" / "schemeup" / "resources"), "schemeup/resources")],
    excludes=["tkinter", "unittest", "pydoc", "test", *unused_qt],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="SchemeUp",
    console=False,
    icon=str(root / "packaging" / "schemeup.ico"),
    version=str(version_file),
    upx=False,
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    upx=False,
    name="SchemeUp",
)
