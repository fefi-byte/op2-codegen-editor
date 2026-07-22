"""Code-Editor mit IDE-artiger Wortvervollständigung (Qt-Bordmittel).

QPlainTextEdit + QCompleter: ab drei getippten Zeichen (oder Strg+Leertaste)
erscheint ein Vorschlags-Popup. Die Wortliste besteht aus der SDK-API
(einmalig aus den OP2MissionSDK-Headern geerntet), einem kuratierten Kern
(TethysGame, MkXY, AddGameMessage, ...) und dynamischen Kontextwörtern
(Missions-Variablen, Gruppennamen, $parameter). Dazu C++-Highlighting
(CppHighlighter) und Auto-Einrückung nach '{'.

Code editor with IDE-style word completion (plain Qt). QPlainTextEdit +
QCompleter: after three typed characters (or Ctrl+Space) a suggestion popup
appears. The word list combines the SDK API (harvested once from the
OP2MissionSDK headers), a curated core (TethysGame, MkXY, AddGameMessage,
...) and dynamic context words (mission variables, group names, $params).
Plus C++ highlighting (CppHighlighter) and auto-indent after '{'.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QCompleter, QPlainTextEdit

from .cpp_highlight import CppHighlighter

# Kuratierter Kern: die Namen, die man im Missions-Code staendig braucht --
# inklusive der Aufruf-Formen, die reines Header-Ernten nicht hergibt.
# Curated core: the names constantly needed in mission code -- including
# call forms that plain header harvesting can't provide.
_CORE_WORDS = [
    "TethysGame::CreateUnit", "TethysGame::AddMessage", "TethysGame::Tick",
    "TethysGame::Time", "TethysGame::GetRand", "TethysGame::NoPlayers",
    "TethysGame::CreateBeacon", "TethysGame::CreateWallOrTube",
    "TethysGame::ForceMoraleGood", "TethysGame::SetEMPMissile",
    "TethysGameEx::MsgBox", "TethysGameEx::SetTopStatusBar",
    "TethysGameEx::SetBottomStatusBar",
    "Player[0]", "Player[1]", "PlayerBuildingEnum", "PlayerVehicleEnum",
    "InRectEnumerator", "InRangeEnumerator", "LocationEnumerator",
    "GroupEnumerator", "ClosestEnumerator",
    "UnitEx", "LOCATION", "MAP_RECT", "MkXY", "MkRect", "XYPos",
    "AddGameMessage", "AddMapMessage", "CreateTimeTrigger",
    "CreateBuildingGroup", "CreateFightGroup", "CreateMiningGroup",
    "op2::log::line", "op2::log::linef", "kTicksPerMark", "g_save",
    "GetCurAction", "GetLastCommand", "IsLive", "IsBuilding", "IsVehicle",
    "DoMove", "DoAttack", "DoRepair", "DoTransfer", "DoStop", "DoIdle",
    "DoUnIdle", "DoSelfDestruct", "DoProduce", "DoLaunch", "GetDamage",
    "OwnerID", "GetType", "Location", "unitID", "moDone", "sndMessage2",
    "snprintf",
]

_KEYWORD_NOISE = frozenset(
    "alignas alignof and asm auto bool break case catch char class const "
    "constexpr continue default define delete double else endif enum explicit "
    "extern false float for friend goto ifdef ifndef include inline int long "
    "namespace new nullptr operator private protected public pragma register "
    "return short signed sizeof static struct switch template this throw true "
    "try typedef typename union unsigned using virtual void volatile while "
    "defined APIENTRY CALLBACK WINAPI BOOL DWORD HWND UINT WPARAM LPARAM "
    "LRESULT TRUE FALSE NULL".split()
)

_sdk_words_cache: list[str] | None = None


def _harvest_sdk_words() -> list[str]:
    """Bezeichner einmalig aus den SDK-Headern ernten (map_ids, Methoden,
    Klassen); ohne SDK-Verzeichnis bleibt es beim kuratierten Kern.

    Harvest identifiers from the SDK headers once (map_ids, methods,
    classes); without the SDK directory the curated core remains."""
    global _sdk_words_cache
    if _sdk_words_cache is not None:
        return _sdk_words_cache
    words: set[str] = set()
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "codegen"))
        import appconfig
        root = appconfig.op2sdk_dir()
        headers = []
        for sub in ("Outpost2DLL/game", "OP2Helper", "HFL/Source"):
            d = root / sub
            if d.is_dir():
                headers.extend(d.glob("*.h"))
        ident = re.compile(r"[A-Za-z_]\w{3,}")
        for h in headers:
            try:
                text = h.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in ident.findall(text):
                if m not in _KEYWORD_NOISE and not m.startswith("_"):
                    words.add(m)
    except Exception:
        pass
    _sdk_words_cache = sorted(words | set(_CORE_WORDS))
    return _sdk_words_cache


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit mit Vervollstaendigung, Highlighting, Auto-Einrueckung.

    QPlainTextEdit with completion, highlighting and auto-indent."""

    MIN_PREFIX = 3

    def __init__(self, parent=None, context_words: list[str] | None = None):
        super().__init__(parent)
        f = self.font()
        f.setFamily("Consolas")
        f.setStyleHint(QFont.Monospace)
        self.setFont(f)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self._highlighter = CppHighlighter(self.document())

        self._context_words: list[str] = list(context_words or [])
        self._model = QStringListModel()
        self._completer = QCompleter(self._model, self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert_completion)
        self._rebuild_model()

    # --- Wortlisten / word lists ---

    def set_context_words(self, words: list[str]):
        """Dynamische Woerter (Variablen, Gruppen, $parameter) austauschen.

        Swap the dynamic words (variables, groups, $params)."""
        self._context_words = [w for w in (words or []) if w]
        self._rebuild_model()

    def _rebuild_model(self):
        # Kontextwoerter zuerst -- bei gleicher Passung stehen die eigenen
        # Namen oben. / Context words first -- own names rank on top.
        seen: set[str] = set()
        ordered: list[str] = []
        for w in list(self._context_words) + _harvest_sdk_words():
            if w not in seen:
                seen.add(w)
                ordered.append(w)
        self._model.setStringList(ordered)

    # --- Vervollstaendigung / completion ---

    def _word_prefix(self) -> str:
        """Woertchen links vom Cursor (inkl. $ und :: als Wortbestandteil).

        The word left of the cursor ($ and :: count as word characters)."""
        cur = self.textCursor()
        text = cur.block().text()[:cur.positionInBlock()]
        m = re.search(r"[\w$:]+$", text)
        return m.group(0) if m else ""

    def _insert_completion(self, completion: str):
        prefix = self._word_prefix()
        cur = self.textCursor()
        for _ in range(len(prefix)):
            cur.deletePreviousChar()
        cur.insertText(completion)
        self.setTextCursor(cur)

    def keyPressEvent(self, e):
        popup = self._completer.popup()
        if popup.isVisible() and e.key() in (
                Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab,
                Qt.Key_Escape, Qt.Key_Up, Qt.Key_Down):
            e.ignore()
            return

        # Strg+Leertaste: Popup erzwingen / Ctrl+Space: force the popup
        force = (e.key() == Qt.Key_Space
                 and e.modifiers() & Qt.ControlModifier)
        if force:
            e.accept()
        else:
            if e.key() in (Qt.Key_Enter, Qt.Key_Return):
                self._auto_indent_return()
                return
            super().keyPressEvent(e)

        prefix = self._word_prefix()
        if not force and (len(prefix) < self.MIN_PREFIX
                          or not e.text().strip()):
            popup.hide()
            return
        if not prefix:
            popup.hide()
            return
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0 or (
                self._completer.completionCount() == 1
                and self._completer.currentCompletion() == prefix):
            popup.hide()
            return
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0)
                      + popup.verticalScrollBar().sizeHint().width())
        self._completer.complete(rect)

    def _auto_indent_return(self):
        """Einrueckung der Vorzeile uebernehmen; nach '{' eine Stufe tiefer.

        Keep the previous line's indentation; one level deeper after '{'."""
        cur = self.textCursor()
        line = cur.block().text()[:cur.positionInBlock()]
        indent = re.match(r"[ \t]*", line).group(0)
        extra = "    " if line.rstrip().endswith("{") else ""
        cur.insertText("\n" + indent + extra)
        self.setTextCursor(cur)
