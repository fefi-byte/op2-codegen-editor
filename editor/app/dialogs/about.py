from __future__ import annotations
from ..common import *
from ..version import VERSION

REPO_URL = "https://github.com/fefi-byte/op2-codegen-editor"


class AboutDialog(QDialog):
    """Hilfe -> Ueber: Banner, Name, Version, Lizenz, Link zum Repository.

    EN: Help -> About: banner, name, version, licence, link to the repository.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        banner = QLabel()
        banner.setPixmap(QPixmap(str(HERE / "resources" / "about_banner.png")))
        lay.addWidget(banner)
        lay.addSpacing(6)

        name = QLabel("OP2 Mission Builder")
        f = name.font(); f.setPointSize(f.pointSize() + 6); f.setBold(True)
        name.setFont(f)
        lay.addWidget(name)
        lay.addWidget(QLabel(tr("about.version", version=VERSION)))
        lay.addWidget(QLabel(tr("about.description")))
        lay.addSpacing(10)

        credit = QLabel(tr("about.credit"))
        credit.setStyleSheet("color: gray;")
        lay.addWidget(credit)
        link = QLabel(f'<a href="{REPO_URL}">{REPO_URL}</a>')
        link.setOpenExternalLinks(True)
        lay.addWidget(link)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
        self.setFixedSize(self.sizeHint())
