from __future__ import annotations
from ..common import *


class OutputDialog(QDialog):
    """Ausgabeort und Dateiname der erzeugten Mission-DLL.

    EN: Output location and file name of the generated mission DLL.
    """
    def __init__(self, parent, out_dir, dll_name):
        super().__init__(parent)
        self.setWindowTitle(tr("output_dialog.title"))
        self.dir_edit = QLineEdit(out_dir)
        browse = QPushButton(tr("output_dialog.browse"))
        browse.clicked.connect(self._browse)
        dir_row = QWidget(); dr = QHBoxLayout(dir_row); dr.setContentsMargins(0, 0, 0, 0)
        dr.addWidget(self.dir_edit, 1); dr.addWidget(browse)

        self.name_edit = QLineEdit(dll_name)

        form = QFormLayout()
        form.addRow(tr("output_dialog.folder"), dir_row)
        form.addRow(tr("output_dialog.filename"), self.name_edit)
        hint = QLabel(tr("output_dialog.hint"))
        hint.setStyleSheet("color: gray;")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form); lay.addWidget(hint); lay.addWidget(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("output_dialog.choose_folder"), self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)


