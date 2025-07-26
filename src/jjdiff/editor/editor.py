from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import override

from jjdiff.tui.console import Console
from jjdiff.tui.drawable import Drawable, Metadata


from ..change import (
    AddBinary,
    AddFile,
    AddSymlink,
    Change,
    ChangeRef,
    DeleteBinary,
    DeleteFile,
    DeleteSymlink,
    Ref,
    LineRef,
    filter_changes,
)
from .cursor import Cursor, ChangeCursor
from .render.changes import render_changes
from .render.markers import SelectionMarker


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


class Editor(Console[Iterable[Change] | None]):
    changes: Sequence[Change]

    included: set[Ref]
    include_dependencies: dict[Ref, set[Ref]]
    include_dependants: dict[Ref, set[Ref]]

    opened: set[ChangeRef]

    undo_stack: list[tuple[Action, set[ChangeRef], Cursor]]
    redo_stack: list[tuple[Action, set[ChangeRef], Cursor]]

    cursor: Cursor

    def __init__(self, changes: Sequence[Change]):
        super().__init__()
        self.changes = changes

        self.included = set()
        self.include_dependencies = {}
        self.include_dependants = {}
        self.add_dependencies()

        self.opened = set()

        self.undo_stack = []
        self.redo_stack = []

        self.cursor = ChangeCursor(0)

        if not changes:
            self.set_result([])

    def add_dependencies(self) -> None:
        self.add_delete_add_dependencies()
        self.add_line_dependencies()

    def add_delete_add_dependencies(self) -> None:
        # Add dependencies between deletes and adds on the same path
        deleted: dict[Path, Ref] = {}

        for change_index, change in enumerate(self.changes):
            match change:
                case DeleteFile(path) | DeleteBinary(path) | DeleteSymlink(path):
                    deleted[path] = ChangeRef(change_index)

                case AddFile(path) | AddBinary(path) | AddSymlink(path):
                    try:
                        dependency = deleted[path]
                    except KeyError:
                        pass
                    else:
                        dependant = ChangeRef(change_index)
                        self.add_dependency(dependant, dependency)

                case _:
                    pass

    def add_line_dependencies(self) -> None:
        # Add dependencies between changes and lines in changes
        for change_index, change in enumerate(self.changes):
            match change:
                case AddFile(_, lines):
                    # All lines in an added file depend on the file being added
                    change_ref = ChangeRef(change_index)
                    for line_index in range(len(lines)):
                        line_ref = LineRef(change_index, line_index)
                        self.add_dependency(line_ref, change_ref)

                case DeleteFile(_, lines):
                    # A deleted file depends on all lines being deleted
                    change_ref = ChangeRef(change_index)
                    for line_index in range(len(lines)):
                        line_ref = LineRef(change_index, line_index)
                        self.add_dependency(change_ref, line_ref)

                case _:
                    pass

    def add_dependency(self, dependant: Ref, dependency: Ref) -> None:
        self.include_dependencies.setdefault(dependant, set()).add(dependency)
        self.include_dependants.setdefault(dependency, set()).add(dependant)

    @override
    def render(self) -> Drawable:
        return render_changes(self.changes, self.cursor, self.included, self.opened)

    @override
    def post_render(self, metadata: Metadata) -> None:
        # Scroll to the selection
        markers = SelectionMarker.get(metadata) or {0: []}
        start = min(markers)
        end = max(markers) + 1
        self.scroll_to(start, end)

    @override
    def handle_key(self, key: str) -> None:
        match key:
            case "ctrl+c" | "ctrl+d" | "escape":
                self.exit()
            case "k" | "up" | "shift+tab":
                self.prev_cursor()
            case "j" | "down" | "tab":
                self.next_cursor()
            case "h" | "left":
                self.grow_cursor()
            case "l" | "right":
                self.shrink_cursor()
            case " ":
                self.select_cursor()
            case "enter":
                self.confirm()
            case "u":
                self.undo()
            case "U":
                self.redo()
            case _:
                pass

    def exit(self) -> None:
        self.set_result(None)

    def prev_cursor(self) -> None:
        self.cursor = self.cursor.prev(self.changes, self.opened)
        self.rerender()

    def next_cursor(self) -> None:
        self.cursor = self.cursor.next(self.changes, self.opened)
        self.rerender()

    def grow_cursor(self) -> None:
        match self.cursor.grow(self.changes, self.opened):
            case ChangeRef(change_index):
                self.opened.remove(ChangeRef(change_index))
            case cursor:
                self.cursor = cursor
        self.rerender()

    def shrink_cursor(self) -> None:
        match self.cursor.shrink(self.changes, self.opened):
            case ChangeRef(change_index):
                self.opened.add(ChangeRef(change_index))
            case cursor:
                self.cursor = cursor
        self.rerender()

    def select_cursor(self) -> None:
        refs = self.cursor.refs(self.changes)
        new_refs = refs - self.included

        if new_refs:
            # Ensure we also include all dependencies
            while dependencies := {
                dependency
                for dependant in refs
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

        self.rerender()
        self.next_cursor()

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

    def confirm(self) -> None:
        self.set_result(filter_changes(self.included, self.changes))

    def apply_action(self, action: Action) -> None:
        self.redo_stack.clear()
        self.undo_stack.append((action, self.opened.copy(), self.cursor))
        action.apply(self)
