from __future__ import annotations

from collections.abc import Callable

import libcst as cst
import libcst.matchers as m
from libcst import helpers
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import ImportItem

from django_autotyping.typing import ModelType

from .base import IMPORT_MATCHER, StubVisitorBasedCodemod
from .constants import OVERLOAD_DECORATOR

MODEL_T_TYPE_VAR = helpers.parse_template_statement('_ModelT = TypeVar("_ModelT", bound=Model)')
"""A statement assigning `_ModelT = TypeVar("_ModelT", bound=Model)`."""

# Matchers:

RELATED_CLASS_DEF_MATCHER = m.ClassDef(
    name=m.SaveMatchedNode(m.Name("ForeignObject") | m.Name("ForeignKey") | m.Name("OneToOneField"), "field_cls_name"),
)
"""Matches all foreign field class definitions that supports parametrization of the `__set__` and `__get__` types."""

MANY_TO_MANY_CLASS_DEF_MATCHER = m.ClassDef(name=m.Name("ManyToManyField"))
"""Matches the `ManyToManyField` class definition."""

INIT_DEF_MATCHER = m.FunctionDef(name=m.Name("__init__"))
"""Matches the `__init__` method definition."""


class ForwardRelationOverloadCodemod(StubVisitorBasedCodemod):
    """A codemod that will add overloads to the `__init__` methods of related fields.

    **Rule identifier**: `DJAS001`.

    **Related settings**:

    - [`ALLOW_PLAIN_MODEL_REFERENCES`][django_autotyping.app_settings.StubsGenerationSettings.ALLOW_PLAIN_MODEL_REFERENCES]
    - [`ALLOW_NONE_SET_TYPE`][django_autotyping.app_settings.StubsGenerationSettings.ALLOW_NONE_SET_TYPE]

    This will provide auto-completion when using [`ForeignKey`][django.db.models.ForeignKey],
    [`OneToOneField`][django.db.models.OneToOneField] and [`ManyToManyField`][django.db.models.ManyToManyField]
    with string references to a model, and accurate type checking when accessing the field attribute
    from a model instance.

    ```python
    class MyModel(models.Model):
        field = models.ForeignKey(
            "myapp.Other",
            on_delete=models.CASCADE,
        )
        nullable = models.OneToOneField(
            "myapp.Other",
            on_delete=models.CASCADE,
            null=True,
        )
    reveal_type(MyModel().field)  # Revealed type is "Other"
    reveal_type(MyModel().nullable)  # Revealed type is "Other | None"
    ```

    ??? abstract "Implementation"
        The following is a snippet of the produced overloads:

        ```python
        class ForeignKey(ForeignObject[_ST, _GT]):
            # For each model, will add two overloads:
            # - 1st: `null: Literal[True]`, which will parametrize `ForeignKey` types as `Optional`.
            # - 2nd: `null: Literal[False] = ...` (the default).
            # `to` is annotated as a `Literal`, with two values: {app_label}.{model_name} and {model_name}.
            @overload
            def __init__(
                self: ForeignKey[MyModel | Combinable | None, MyModel | None],
                to: Literal["MyModel", "myapp.MyModel"],
                ...
            ) -> None: ...
        ```
    """  # noqa: E501

    STUB_FILES = {"db/models/fields/related.pyi"}

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

    def transform_module(self, tree: cst.Module) -> cst.Module:
        return tree.visit(self)

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        body = list(updated_node.body)
        last_import = next((node for node in reversed(body) if m.matches(node, IMPORT_MATCHER)), None)
        index = body.index(last_import) + 1 if last_import is not None else 0
        body[index:index] = [*_import_statements(self.django_context.model_imports), MODEL_T_TYPE_VAR]
        return updated_node.with_changes(body=body)

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        class_name = original_node.name.value
        if class_name == "ManyToManyField":
            return self._replace_init_overloads(updated_node, self._build_many_to_many_overloads)
        if class_name in {"ForeignObject", "ForeignKey", "OneToOneField"}:
            return self._replace_init_overloads(
                updated_node, lambda init_def: self._build_related_field_overloads(init_def, class_name)
            )
        return updated_node

    def _replace_init_overloads(
        self,
        class_def: cst.ClassDef,
        build_overloads: Callable[[cst.FunctionDef], list[cst.FunctionDef]],
    ) -> cst.ClassDef:
        body = []
        replaced = False
        for statement in class_def.body.body:
            if not replaced and m.matches(statement, INIT_DEF_MATCHER):
                body.extend(build_overloads(helpers.ensure_type(statement, cst.FunctionDef)))
                replaced = True
                continue
            body.append(statement)
        return class_def.with_changes(body=class_def.body.with_changes(body=body))

    def _build_many_to_many_overloads(self, init_def: cst.FunctionDef) -> list[cst.FunctionDef]:
        """Add the necessary overloads for `ManyToManyField`'s `__init__` method.

        Due to combinatorial explosion, we can't add overloads that would handle `through` models alongside with `to`.
        """
        base_code = _function_code(init_def.with_changes(decorators=[OVERLOAD_DECORATOR]))
        overloads: list[str] = []

        for model in self.django_context.models:
            model_name = self.django_context.get_model_name(model)
            allow_plain_model_name = (
                self.stubs_settings.ALLOW_PLAIN_MODEL_REFERENCES and not self.django_context.is_duplicate(model)
            )

            overloads.append(
                _with_param_annotations(
                    base_code,
                    self_annotation=f"ManyToManyField[{model_name}, _Through]",
                    to_annotation=_build_to_annotation(model, allow_plain_model_name),
                )
            )

        overloads.append(
            # Match against a real model type. This removes the `| str` part so type checkers infer `self`.
            _with_param_annotations(base_code, to_annotation="type[_To]")
        )
        overloads.append(
            "@overload\n"
            "def __init__(self, to: type[Model] | str, *args: Any, "
            "through: type[Model] | str | None = None, **kwargs: Any) -> None: ...\n"
        )

        return _parse_function_block(overloads)

    def _build_related_field_overloads(self, init_def: cst.FunctionDef, field_cls_name: str) -> list[cst.FunctionDef]:
        """Add the necessary overloads to foreign fields that supports
        that supports parametrization of the `__set__` and `__get__` types.
        """
        base_code = _function_code(init_def.with_changes(decorators=[OVERLOAD_DECORATOR]))
        overloads: list[str] = []

        # For each model, create two overloads, depending on the `null` value:
        for model in self.django_context.models:
            model_name = self.django_context.get_model_name(model)
            allow_plain_model_name = (
                self.stubs_settings.ALLOW_PLAIN_MODEL_REFERENCES and not self.django_context.is_duplicate(model)
            )

            for nullable in (True, False):  # Order matters!
                overloads.append(
                    _with_param_annotations(
                        base_code,
                        self_annotation=_build_self_annotation(
                            field_cls_name, model_name, nullable, self.stubs_settings.ALLOW_NONE_SET_TYPE
                        ),
                        to_annotation=_build_to_annotation(model, allow_plain_model_name),
                        null_annotation=f"Literal[{nullable}]",
                        null_has_default=not nullable,
                    )
                )

        for nullable in (True, False):  # Order matters!
            overloads.append(
                _with_param_annotations(
                    base_code,
                    to_annotation="type[_ModelT]",
                    self_annotation=_build_self_annotation(
                        field_cls_name, "_ModelT", nullable, self.stubs_settings.ALLOW_NONE_SET_TYPE
                    ),
                    null_annotation=f"Literal[{nullable}]",
                    null_has_default=not nullable,
                )
            )

        for nullable in (True, False):  # Order matters!
            overloads.append(
                _with_param_annotations(
                    base_code,
                    to_annotation="str",
                    self_annotation=_build_self_annotation(
                        field_cls_name, "Model", nullable, self.stubs_settings.ALLOW_NONE_SET_TYPE
                    ),
                    null_annotation=f"Literal[{nullable}]",
                    null_has_default=not nullable,
                )
            )

        overloads.append(_related_field_fallback_overload(field_cls_name))

        return _parse_function_block(overloads)


def _build_self_annotation(field_cls_name: str, model_name: str, nullable: bool, allow_none_set_type: bool) -> str:
    """Builds the `self` annotation of foreign fields.

    With `field_cls_name="ForeignKey"`, `model_name="MyModel"` and `nullable=False`, the following is produced:

    >>> ForeignKey[MyModel | None, MyModel]

    (Even if not nullable, the `__set__` type can still be `None`. Having a foreign instance is only enforced on save).
    """
    set_type = f"{model_name} | Combinable | None" if allow_none_set_type or nullable else f"{model_name} | Combinable"
    get_type = f"{model_name} | None" if nullable else model_name
    return f"{field_cls_name}[{set_type}, {get_type}]"


def _build_to_annotation(model: ModelType, allow_plain_model_name: bool) -> str:
    """Builds the `to` annotation of foreign fields.

    This will result in a `Literal` with two string values, the model name and the dotted app label and model name.
    If `allow_plain_model_name` is set to `False`, only the second literal value will be set.
    """
    literals = [f'"{model._meta.app_label}.{model.__name__}"']
    if allow_plain_model_name:
        literals.insert(0, f'"{model.__name__}"')

    return f"Literal[{', '.join(literals)}]"


def _related_field_fallback_overload(field_cls_name: str) -> str:
    if field_cls_name == "ForeignObject":
        return (
            "@overload\n"
            "def __init__(self, to: type[Model] | str, on_delete: Callable[..., None], "
            "from_fields: Sequence[str], to_fields: Sequence[str], *args: Any, **kwargs: Any) -> None: ...\n"
        )
    return (
        "@overload\n"
        "def __init__(self, to: type[Model] | str, on_delete: Callable[..., None], "
        "*args: Any, **kwargs: Any) -> None: ...\n"
    )


def _function_code(function: cst.FunctionDef) -> str:
    return cst.Module([]).code_for_node(function)


def _parse_function_block(functions: list[str]) -> list[cst.FunctionDef]:
    return [
        helpers.ensure_type(statement, cst.FunctionDef) for statement in cst.parse_module("\n".join(functions)).body
    ]


def _import_statements(model_imports: list[ImportItem]) -> list[cst.SimpleStatementLine]:
    imports = [
        helpers.parse_template_statement("from django.db.models.expressions import Combinable"),
        helpers.parse_template_statement("from typing import Literal, TypeVar, overload"),
    ]
    for model_import in model_imports:
        obj_name = model_import.obj_name
        if obj_name is None:
            imports.append(helpers.parse_template_statement(f"import {model_import.module_name}"))
            continue
        imported = f"{obj_name} as {model_import.alias}" if model_import.alias is not None else obj_name
        imports.append(helpers.parse_template_statement(f"from {model_import.module_name} import {imported}"))
    return imports


def _with_param_annotations(
    code: str,
    *,
    self_annotation: str | None = None,
    to_annotation: str | None = None,
    null_annotation: str | None = None,
    null_has_default: bool = True,
) -> str:
    lines = code.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        leading = line[: len(line) - len(line.lstrip())]
        if self_annotation is not None and stripped == "self,":
            lines[index] = f"{leading}self: {self_annotation},"
        elif to_annotation is not None and stripped.startswith("to: ") and stripped.endswith(","):
            lines[index] = f"{leading}to: {to_annotation},"
        elif null_annotation is not None and stripped.startswith("null: ") and stripped.endswith(","):
            default = " = ..." if null_has_default else ""
            lines[index] = f"{leading}null: {null_annotation}{default},"
    return "\n".join(lines) + "\n"
