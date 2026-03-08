"""
Shopping list tool — a shared family shopping list.

Items stored at ~/.amini/data/shopping_list.json as a list of dicts:
    { "item": str, "quantity": str, "added_by": str, "done": bool }

The LLM calls these tools to add, query, or check off items.
"""

import json
import logging
from pathlib import Path

from agents.tools.base_tool import BaseTool, ToolParam

logger = logging.getLogger(__name__)


class ShoppingAddTool(BaseTool):
    """Add an item to the shared family shopping list."""

    name = "shopping_add"
    description = "Add an item (or items) to the family shopping list."
    parameters = [
        ToolParam("item", "string", "Item to add, e.g. 'milk', 'bread'"),
        ToolParam("quantity", "string", "Quantity or amount, e.g. '2 litres' (optional)", required=False),
        ToolParam("added_by", "string", "Name of the person adding the item (optional)", required=False),
    ]

    def __init__(self, list_path: Path):
        self._path = list_path

    def execute(self, item: str, quantity: str = "", added_by: str = "") -> str:
        items = _load(self._path)
        # Avoid exact duplicates that are not yet done
        existing = [i for i in items if i["item"].lower() == item.lower() and not i["done"]]
        if existing:
            return f"'{item}' is already on the list."
        items.append({"item": item, "quantity": quantity, "added_by": added_by, "done": False})
        _save(self._path, items)
        who = f" (added by {added_by})" if added_by else ""
        qty = f" — {quantity}" if quantity else ""
        logger.info("Shopping: added '%s'%s%s", item, qty, who)
        return f"Added {item}{qty} to the shopping list{who}."


class ShoppingQueryTool(BaseTool):
    """Read out the current shopping list."""

    name = "shopping_query"
    description = "Read the current family shopping list."
    parameters = []

    def __init__(self, list_path: Path):
        self._path = list_path

    def execute(self) -> str:
        items = _load(self._path)
        pending = [i for i in items if not i["done"]]
        if not pending:
            return "The shopping list is empty."
        parts = []
        for i in pending:
            qty = f" ({i['quantity']})" if i.get("quantity") else ""
            parts.append(f"{i['item']}{qty}")
        return "Shopping list: " + ", ".join(parts) + "."


class ShoppingDoneTool(BaseTool):
    """Mark an item as purchased / remove it from the list."""

    name = "shopping_done"
    description = "Mark an item as purchased on the shopping list."
    parameters = [
        ToolParam("item", "string", "The item to mark as done"),
    ]

    def __init__(self, list_path: Path):
        self._path = list_path

    def execute(self, item: str) -> str:
        items = _load(self._path)
        matched = False
        for i in items:
            if i["item"].lower() == item.lower() and not i["done"]:
                i["done"] = True
                matched = True
                break
        if not matched:
            return f"'{item}' was not found on the shopping list."
        _save(self._path, items)
        return f"Marked '{item}' as done."


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(path: Path, items: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2))
