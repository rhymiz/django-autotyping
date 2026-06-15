from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst import helpers
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor

from .base import StubVisitorBasedCodemod

TEST_CASE_MATCHER = m.ClassDef(name=m.Name("TestCase"))
SIMPLE_TEST_CASE_MATCHER = m.ClassDef(name=m.Name("SimpleTestCase"))

CAPTURE_ON_COMMIT_CALLBACKS_DEF = helpers.parse_template_statement(
    """
@classmethod
def captureOnCommitCallbacks(
    cls, *, using: str = ..., execute: bool = ...
) -> AbstractContextManager[list[Callable[[], None]]]: ...
"""
)

ASSERT_FORM_ERROR_DEF = helpers.parse_template_statement(
    """
def assertFormError(
    self,
    form: BaseForm,
    field: str | None,
    errors: list[str] | str,
    msg_prefix: str = ...,
) -> None: ...
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
        AddImportsVisitor.add_needed_import(context, module="django.forms.forms", obj="BaseForm")

    @m.leave(SIMPLE_TEST_CASE_MATCHER)
    def mutate_simple_test_case_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        has_method = False
        body = [
            ASSERT_FORM_ERROR_DEF if m.matches(statement, m.FunctionDef(name=m.Name("assertFormError"))) else statement
            for statement in updated_node.body.body
        ]
        for statement in updated_node.body.body:
            if m.matches(statement, m.FunctionDef(name=m.Name("assertFormError"))):
                has_method = True
                break

        if has_method:
            return updated_node.with_changes(body=updated_node.body.with_changes(body=body))

        return updated_node.with_changes(
            body=updated_node.body.with_changes(
                body=[*body, ASSERT_FORM_ERROR_DEF],
            ),
        )

    @m.leave(TEST_CASE_MATCHER)
    def mutate_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        has_method = False
        body = [
            CAPTURE_ON_COMMIT_CALLBACKS_DEF
            if m.matches(statement, m.FunctionDef(name=m.Name("captureOnCommitCallbacks")))
            else statement
            for statement in updated_node.body.body
        ]
        for statement in updated_node.body.body:
            if m.matches(statement, m.FunctionDef(name=m.Name("captureOnCommitCallbacks"))):
                has_method = True
                break

        if has_method:
            return updated_node.with_changes(body=updated_node.body.with_changes(body=body))

        return updated_node.with_changes(
            body=updated_node.body.with_changes(
                body=[*body, CAPTURE_ON_COMMIT_CALLBACKS_DEF],
            ),
        )
