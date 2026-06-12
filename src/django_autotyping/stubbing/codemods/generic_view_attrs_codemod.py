from __future__ import annotations

import libcst as cst
import libcst.matchers as m

from .base import StubVisitorBasedCodemod

GENERIC_VIEW_ATTRS = {
    "SingleObjectMixin": "object: models.Model",
    "MultipleObjectMixin": "object_list: _BaseQuerySet[Any]",
}


class GenericViewAttrsCodemod(StubVisitorBasedCodemod):
    """A codemod that exposes runtime attributes set by Django generic views.

    **Rule identifier**: `DJAS021`.
    """

    STUB_FILES = {"views/generic/detail.pyi", "views/generic/list.pyi"}

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        member = GENERIC_VIEW_ATTRS.get(original_node.name.value)
        if member is None:
            return updated_node

        target_name = member.split(":", maxsplit=1)[0]
        if any(
            m.matches(statement, m.SimpleStatementLine(body=[m.AnnAssign(target=m.Name(target_name))]))
            for statement in updated_node.body.body
        ):
            return updated_node

        return updated_node.with_changes(
            body=updated_node.body.with_changes(
                body=[
                    cst.parse_statement(f"{member}\n"),
                    *updated_node.body.body,
                ],
            ),
        )
