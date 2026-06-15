from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst import helpers

from .base import StubVisitorBasedCodemod

CONTEXT_LIST_MATCHER = m.ClassDef(name=m.Name("ContextList"))

CONTEXT_LIST_GETITEM_OVERLOADS = [
    helpers.parse_template_statement(
        """
@overload
def __getitem__(self, key: str) -> _T: ...
"""
    ),
    helpers.parse_template_statement(
        """
@overload
def __getitem__(self, key: int) -> Mapping[str, _T]: ...
"""
    ),
    helpers.parse_template_statement(
        """
@overload
def __getitem__(self, key: slice) -> list[Mapping[str, _T]]: ...
"""
    ),
]


class TestContextCodemod(StubVisitorBasedCodemod):
    """A codemod that exposes Django test context string lookups.

    **Rule identifier**: `DJAS019`.
    """

    STUB_FILES = {"test/utils.pyi"}

    @m.leave(CONTEXT_LIST_MATCHER)
    def mutate_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if any(m.matches(statement, m.FunctionDef(name=m.Name("__getitem__"))) for statement in updated_node.body.body):
            return updated_node

        return updated_node.with_changes(
            body=updated_node.body.with_changes(
                body=[*updated_node.body.body, *CONTEXT_LIST_GETITEM_OVERLOADS],
            ),
        )
