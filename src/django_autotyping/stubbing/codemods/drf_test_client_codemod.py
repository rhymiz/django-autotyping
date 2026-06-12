from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst import helpers
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor

from .base import StubVisitorBasedCodemod

SIMPLE_TEST_CASE_MATCHER = m.ClassDef(name=m.Name("SimpleTestCase"))


class DRFTestClientCodemod(StubVisitorBasedCodemod):
    """A codemod that exposes DRF's APIClient on Django test cases.

    **Rule identifier**: `DJAS018`.

    **Related settings**:

    - [`DRF_TEST_CLIENT`][django_autotyping.app_settings.StubsGenerationSettings.DRF_TEST_CLIENT].
    """

    STUB_FILES = {"test/testcases.pyi"}

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        if self.stubs_settings.DRF_TEST_CLIENT:
            AddImportsVisitor.add_needed_import(context, module="rest_framework.test", obj="APIClient")

    @m.leave(SIMPLE_TEST_CASE_MATCHER)
    def mutate_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if not self.stubs_settings.DRF_TEST_CLIENT:
            return updated_node

        body = [
            _replace_annotation(statement, "client_class", "type[APIClient]")
            or _replace_annotation(statement, "client", "APIClient")
            or statement
            for statement in updated_node.body.body
        ]
        return updated_node.with_changes(body=updated_node.body.with_changes(body=body))


def _replace_annotation(
    statement: cst.BaseStatement,
    name: str,
    annotation: str,
) -> cst.SimpleStatementLine | None:
    if not m.matches(
        statement,
        m.SimpleStatementLine(body=[m.AnnAssign(target=m.Name(name))]),
    ):
        return None

    statement = helpers.ensure_type(statement, cst.SimpleStatementLine)
    assignment = helpers.ensure_type(statement.body[0], cst.AnnAssign)
    return statement.with_changes(
        body=[
            assignment.with_changes(
                annotation=cst.Annotation(helpers.parse_template_expression(annotation)),
            )
        ],
    )
