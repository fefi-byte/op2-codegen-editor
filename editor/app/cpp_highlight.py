"""Einfaches C++-Syntax-Highlighting fuer die Code-Vorschau (LevelMain.cpp).

Ein QSyntaxHighlighter mit Regeln fuer Schluesselwoerter, SDK-Typen,
Funktionsaufrufe, Zahlen, Strings, Praeprozessor- und Kommentarzeilen
(inkl. mehrzeiliger /* */-Bloecke). Farben im VS-Code-"Dark+"-Stil; das
Textfeld sollte daher einen dunklen Hintergrund haben.

Simple C++ syntax highlighting for the code preview (LevelMain.cpp).

A QSyntaxHighlighter with rules for keywords, SDK types, function calls,
numbers, strings, preprocessor and comment lines (including multi-line
/* */ blocks). Colors follow the VS Code "Dark+" style, so the text field
should use a dark background.
"""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

# C++-Schluesselwoerter / C++ keywords
_KEYWORDS = (
    "alignas alignof and asm auto bool break case catch char class const "
    "constexpr continue default delete do double else enum explicit extern "
    "false float for friend goto if inline int long mutable namespace new "
    "nullptr operator private protected public register return short signed "
    "sizeof static struct switch template this throw true try typedef typename "
    "union unsigned using virtual void volatile while"
).split()

# Haeufige OP2-SDK-Typen/-Klassen / common OP2 SDK types & classes
_TYPES = (
    "UnitEx Trigger LOCATION MAP_RECT ScGroup BuildingGroup MiningGroup "
    "Player TethysGame PlayerBuildingEnum MissionTypes Export"
).split()


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    """Erzeugt ein QTextCharFormat mit Farbe/Stil.

    Builds a QTextCharFormat with the given color/style.
    """
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class CppHighlighter(QSyntaxHighlighter):
    """C++-Highlighter fuer den generierten Quelltext.

    C++ highlighter for the generated source code.
    """

    def __init__(self, document):
        super().__init__(document)
        self._comment_fmt = _fmt("#6A9955", italic=True)
        # Regeln in Reihenfolge; spaetere ueberschreiben fruehere, daher
        # Strings/Kommentare zuletzt (gewinnen ueber Schluesselwoerter).
        # Rules in order; later ones override earlier ones, so strings and
        # comments come last (they win over keywords).
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        kw_fmt = _fmt("#569CD6", bold=True)
        for word in _KEYWORDS:
            self._rules.append((QRegularExpression(rf"\b{word}\b"), kw_fmt))
        type_fmt = _fmt("#4EC9B0")
        for word in _TYPES:
            self._rules.append((QRegularExpression(rf"\b{word}\b"), type_fmt))
        # Zahlen / numbers
        self._rules.append((QRegularExpression(r"\b[0-9]+\b"), _fmt("#B5CEA8")))
        # Funktionsaufrufe: Bezeichner direkt vor '(' / function calls: name before '('
        self._rules.append(
            (QRegularExpression(r"\b[A-Za-z_]\w*(?=\s*\()"), _fmt("#DCDCAA")))
        # Strings "..." / string literals
        self._rules.append((QRegularExpression(r"\"[^\"]*\""), _fmt("#CE9178")))
        # Praeprozessor (#include, #define, ...) / preprocessor lines
        self._rules.append((QRegularExpression(r"^\s*#.*"), _fmt("#C586C0")))
        # Einzeilige Kommentare // ... / single-line comments
        self._rules.append((QRegularExpression(r"//[^\n]*"), self._comment_fmt))
        # Grenzen mehrzeiliger Kommentare / multi-line comment delimiters
        self._block_start = QRegularExpression(r"/\*")
        self._block_end = QRegularExpression(r"\*/")

    def highlightBlock(self, text: str) -> None:
        # Einzeilige Regeln anwenden / apply the single-line rules
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
        # Mehrzeilige /* */-Bloecke ueber Zeilengrenzen hinweg verfolgen.
        # Track multi-line /* */ blocks across line boundaries.
        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() != 1:
            m = self._block_start.match(text)
            start = m.capturedStart() if m.hasMatch() else -1
        while start >= 0:
            m_end = self._block_end.match(text, start)
            if m_end.hasMatch():
                length = m_end.capturedEnd() - start
                self.setFormat(start, length, self._comment_fmt)
                m = self._block_start.match(text, start + length)
                start = m.capturedStart() if m.hasMatch() else -1
            else:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self._comment_fmt)
                break
