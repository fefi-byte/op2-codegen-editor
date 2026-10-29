"""Verschachtelter Aktions-Editor (Home-Assistant-Stil, Karten).

ActionListWidget rendert eine Liste von Aktionen als Karten + "+ Aktion".
Eine if-Aktion (kind == "if") ist eine Karte mit Wenn/Dann/Sonst, wobei Dann
und Sonst wieder ActionListWidgets enthalten (rekursiv).

Nested action editor (Home-Assistant style, card-based).
ActionListWidget renders a list of actions as cards plus a "+ Action" button.
An "if" action (kind == "if") is a card with When/Then/Else, where Then and
Else again contain ActionListWidgets (recursive nesting).
"""
# Der Editor ist auf Module verteilt: action_daten (Konstanten), condition_dialog,
# action_form (+ action_form_felder, action_form_listen) und action_cards.
# The editor is split across modules; this one re-exports the public classes.
from .action_daten import produce_items_for, unit_commands_for  # noqa: F401
from .condition_dialog import ConditionEditDialog  # noqa: F401
from .action_form import ActionInlineForm  # noqa: F401
from .action_cards import ConditionListWidget, ActionListWidget, ActionCard  # noqa: F401
