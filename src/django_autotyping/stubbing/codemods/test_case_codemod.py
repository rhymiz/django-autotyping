from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst import helpers
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor

from .base import StubVisitorBasedCodemod

TEST_CASE_MATCHER = m.ClassDef(name=m.Name("TestCase"))

CAPTURE_ON_COMMIT_CALLBACKS_DEF = helpers.parse_template_statement(
    """
@classmethod
def captureOnCommitCallbacks(
    cls, *, using: str = ..., execute: bool = ...
) -> AbstractContextManager[list[Callable[[], Any]]]: ...
"""
)


class TestCaseCodemod(StubVisitorBasedCodemod):
    """A codemod that exposes Django ``TestCase`` helpers missing from upstream stubs.

    **Rule identifier**: `DJAS020`.
    """

    STUB_FILES = {"test/testcases.pyi"}

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        AddImportsVisitor.add_needed_import(context, module="contextlib", obj="AbstractContextManager")

    @m.leave(TEST_CASE_MATCHER)
    def mutate_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if any(
            m.matches(statement, m.FunctionDef(name=m.Name("captureOnCommitCallbacks")))
            for statement in updated_node.body.body
        ):
            return updated_node

        return updated_node.with_changes(
            body=updated_node.body.with_changes(
                body=[*updated_node.body.body, CAPTURE_ON_COMMIT_CALLBACKS_DEF],
            ),
        )
