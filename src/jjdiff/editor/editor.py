from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence, Set
from typing import override

from jjdiff.config import get_config
from jjdiff.tui.console import Console
from jjdiff.tui.drawable import Drawable
from jjdiff.tui.keyboard import Key
from jjdiff.tui.scroll import State
from jjdiff.tui.text import TextStyle

from ..change import (
    Change,
    ChangeRef,
    Ref,
    get_all_refs,
    get_dependencies,
    is_change_deprioritized,
)
from .cursor import ChangeCursor, Cursor
from .render.changes import render_changes
from .render.markers import SelectionMarker

SCROLLBAR_STYLE = TextStyle(fg="bright black")


class Action(ABC):
    @abstractmethod
    def apply(self, editor: "Editor") -> None:
        raise NotImplementedError

    @abstractmethod
    def revert(self, editor: "Editor") -> None:
        raise NotImplementedError


class AddIncludes(Action):
    refs: set[Ref]

    def __init__(self, refs: set[Ref]):
        self.refs = refs

    @override
    def apply(self, editor: "Editor") -> None:
        editor.included |= self.refs

    @override
    def revert(self, editor: "Editor") -> None:
        editor.included -= self.refs


class RemoveIncludes(Action):
    refs: set[Ref]

    def __init__(self, refs: set[Ref]):
        self.refs = refs

    @override
    def apply(self, editor: "Editor") -> None:
        editor.included -= self.refs

    @override
    def revert(self, editor: "Editor") -> None:
        editor.included |= self.refs


class Editor(Console[Set[Ref] | None]):
    changes: Sequence[Change]

    included: set[Ref]
    include_dependencies: dict[Ref, set[Ref]]
    include_dependants: dict[Ref, set[Ref]]

    opened: set[ChangeRef]

    undo_stack: list[tuple[Action, set[ChangeRef], Cursor]]
    redo_stack: list[tuple[Action, set[ChangeRef], Cursor]]

    cursor: Cursor

    def __init__(self, changes: Sequence[Change]):
        super().__init__(SCROLLBAR_STYLE)
        self.changes = changes

        self.included = set()
        self.include_dependencies = {}
        self.include_dependants = {}

        for dependency, dependant in get_dependencies(changes):
            self.include_dependencies.setdefault(dependant, set()).add(dependency)
            self.include_dependants.setdefault(dependency, set()).add(dependant)

        self.opened = set()

        self.undo_stack = []
        self.redo_stack = []

        self.cursor = ChangeCursor(0)

        if not changes:
            self.set_result(frozenset())

        if get_config().editor.default_open:
            self.opened.update(
                ChangeRef(change_index)
                for change_index, change in enumerate(changes)
                if not is_change_deprioritized(change)
            )

    @override
    def render(self) -> Drawable:
        return render_changes(self.changes, self.cursor, self.included, self.opened)

    @override
    def post_render(self, state: State) -> None:
        # Scroll to the selection
        markers = state.get_markers(SelectionMarker) or {0: []}
        start = min(markers)
        end = max(markers) + 1
        state.scroll_to(start, end)

    @override
    def handle_key(self, key: Key) -> None:
        try:
            command = get_config().keymap[key]
        except KeyError:
            return
        else:
            getattr(self, command)()

    def exit(self) -> None:
        self.set_result(None)

    def prev_cursor(self) -> None:
        self.move_cursor(self.cursor.prev(self.changes, self.opened))

    def next_cursor(self) -> None:
        self.move_cursor(self.cursor.next(self.changes, self.opened))

    def first_cursor(self) -> None:
        self.move_cursor(self.cursor.first(self.changes, self.opened))

    def last_cursor(self) -> None:
        self.move_cursor(self.cursor.last(self.changes, self.opened))

    def move_cursor(self, new_cursor: Cursor) -> None:
        if (
            new_cursor.change != self.cursor.change
            and get_config().editor.auto_open
            and ChangeRef(self.cursor.change) in self.opened
        ):
            self.opened.remove(ChangeRef(self.cursor.change))
            self.opened.add(ChangeRef(new_cursor.change))

        self.cursor = new_cursor
        self.rerender()

    def grow_cursor(self) -> None:
        match self.cursor.grow(self.changes, self.opened):
            case ChangeRef() as ref:
                self.opened.remove(ref)
            case cursor:
                self.cursor = cursor
        self.rerender()

    def shrink_cursor(self) -> None:
        match self.cursor.shrink(self.changes, self.opened):
            case ChangeRef() as ref:
                self.opened.add(ref)
            case cursor:
                self.cursor = cursor
        self.rerender()

    def select_cursor(self) -> None:
        refs = self.cursor.refs(self.changes)
        self.select_refs(refs)
        self.next_cursor()

    def select_all(self) -> None:
        refs = get_all_refs(self.changes)
        self.select_refs(refs)
        self.rerender()

    def select_refs(self, refs: Iterable[Ref]) -> None:
        refs = set(refs)
        new_refs = refs - self.included

        if new_refs:
            # Ensure we also include all dependencies (transitively)
            while dependencies := {
                dependency
                for dependant in new_refs
                for dependency in self.include_dependencies.get(dependant, set())
                if dependency not in new_refs
            }:
                new_refs.update(dependencies)

            # Remove dependencies that were already included
            new_refs.difference_update(self.included)

            self.apply_action(AddIncludes(new_refs))
        else:
            # Ensure we also include all dependants
            while dependants := {
                dependant
                for dependency in refs
                for dependant in self.include_dependants.get(dependency, set())
                if dependant not in refs
            }:
                refs.update(dependants)

            # Remove dependencies that are not included
            refs.intersection_update(self.included)

            self.apply_action(RemoveIncludes(refs))

    def undo(self) -> None:
        try:
            action, opened, cursor = self.undo_stack.pop()
        except IndexError:
            return

        self.redo_stack.append((action, self.opened, self.cursor))
        action.revert(self)
        self.opened = opened
        self.cursor = cursor
        self.rerender()

    def redo(self) -> None:
        try:
            action, opened, cursor = self.redo_stack.pop()
        except IndexError:
            return

        self.undo_stack.append((action, self.opened, self.cursor))
        action.apply(self)
        self.opened = opened
        self.cursor = cursor
        self.rerender()

    def open_all(self) -> None:
        self.opened.update(
            ChangeRef(change_index) for change_index in range(len(self.changes))
        )
        self.rerender()

    def close_all(self) -> None:
        self.cursor = ChangeCursor(self.cursor.change)
        self.opened.clear()
        self.rerender()

    def confirm(self) -> None:
        self.set_result(frozenset(self.included))

    def apply_action(self, action: Action) -> None:
        self.redo_stack.clear()
        self.undo_stack.append((action, self.opened.copy(), self.cursor))
        action.apply(self)
