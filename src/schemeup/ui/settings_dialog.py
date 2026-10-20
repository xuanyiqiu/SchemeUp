"""The settings dialog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.settings import Settings


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        library_path: Path,
        default_backups: Path,
        backup_now: Callable[[], Path | None],
        hotkey_supported: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))
        self.setMinimumWidth(520)
        self._settings = settings
        self._default_backups = default_backups
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.theme = QComboBox()
        for value, label in (
            ("system", self.tr("Same as Windows")),
            ("light", self.tr("Light")),
            ("dark", self.tr("Dark")),
        ):
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(max(self.theme.findData(settings.theme), 0))
        form.addRow(self.tr("Appearance"), self.theme)

        self.language = QComboBox()
        for value, label in (
            ("system", self.tr("Same as the system")),
            ("en", "English"),
            ("es", "Español"),
        ):
            self.language.addItem(label, value)
        self.language.setCurrentIndex(max(self.language.findData(settings.language), 0))
        form.addRow(self.tr("Language"), self.language)

        self.motion = QComboBox()
        for value, label in (
            ("system", self.tr("Follow the system")),
            ("full", self.tr("Full (springs and inertia)")),
            ("reduced", self.tr("Reduced (no animation)")),
        ):
            self.motion.addItem(label, value)
        self.motion.setCurrentIndex(max(self.motion.findData(settings.motion), 0))
        form.addRow(self.tr("Motion"), self.motion)

        self.hotkey = QKeySequenceEdit(QKeySequence(settings.hotkey))
        self.hotkey.setMaximumSequenceLength(1)
        hotkey_row = QWidget()
        hotkey_layout = QVBoxLayout(hotkey_row)
        hotkey_layout.setContentsMargins(0, 0, 0, 0)
        hotkey_layout.addWidget(self.hotkey)
        if not hotkey_supported:
            note = QLabel(
                self.tr(
                    "Global shortcuts work on Windows. Elsewhere, bind"
                    " “schemeup --capture” to a key."
                )
            )
            note.setObjectName("muted")
            note.setWordWrap(True)
            hotkey_layout.addWidget(note)
        form.addRow(self.tr("Quick capture shortcut"), hotkey_row)

        self.close_to_tray = QCheckBox(
            self.tr("Keep running in the tray when the window is closed")
        )
        self.close_to_tray.setChecked(settings.close_to_tray)
        form.addRow("", self.close_to_tray)

        backups = QWidget()
        backups_layout = QHBoxLayout(backups)
        backups_layout.setContentsMargins(0, 0, 0, 0)
        self.backups_dir = QLineEdit(settings.backups_dir or str(default_backups))
        browse = QPushButton(self.tr("Browse…"))
        browse.clicked.connect(self._browse)
        now = QPushButton(self.tr("Back up now"))
        now.clicked.connect(lambda: self._backup(backup_now))
        backups_layout.addWidget(self.backups_dir, 1)
        backups_layout.addWidget(browse)
        backups_layout.addWidget(now)
        form.addRow(self.tr("Daily backups"), backups)
        self.backup_status = QLabel()
        self.backup_status.setObjectName("muted")
        form.addRow("", self.backup_status)

        location = QWidget()
        location_layout = QHBoxLayout(location)
        location_layout.setContentsMargins(0, 0, 0, 0)
        path_label = QLabel(str(library_path))
        path_label.setObjectName("muted")
        path_label.setWordWrap(True)
        open_folder = QPushButton(self.tr("Show"))
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(library_path.parent)))
        )
        location_layout.addWidget(path_label, 1)
        location_layout.addWidget(open_folder)
        form.addRow(self.tr("Library file"), location)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, self.tr("Backup folder"), self.backups_dir.text()
        )
        if chosen:
            self.backups_dir.setText(chosen)

    def _backup(self, backup_now: Callable[[], Path | None]) -> None:
        path = backup_now()
        self.backup_status.setText(
            self.tr("Saved %1").replace("%1", str(path)) if path else self.tr("Backup failed")
        )

    def result_settings(self) -> Settings:
        backups = self.backups_dir.text().strip()
        return replace(
            self._settings,
            theme=str(self.theme.currentData()),
            language=str(self.language.currentData()),
            motion=str(self.motion.currentData()),
            hotkey=self.hotkey.keySequence().toString() or self._settings.hotkey,
            close_to_tray=self.close_to_tray.isChecked(),
            backups_dir="" if backups == str(self._default_backups) else backups,
        )
