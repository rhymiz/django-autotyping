from __future__ import annotations

from abc import ABC, abstractmethod
from itertools import product
from typing import ClassVar, TypedDict, cast

import libcst as cst
from django.db.models import (
    AutoField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    Field,
    FloatField,
    GenericIPAddressField,
    IntegerField,
    IPAddressField,
    TextField,
    TimeField,
    UUIDField,
)
from django.db.models.fields.reverse_related import ForeignObjectRel
from libcst import helpers
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor, ImportItem
from libcst.metadata import ScopeProvider

from django_autotyping._compat import Required
from django_autotyping.typing import FlattenFunctionDef

from ._utils import TypedDictAttribute, build_typed_dict, get_param, to_pascal
from .base import InsertAfterImportsVisitor, StubVisitorBasedCodemod
from .constants import OVERLOAD_DECORATOR

MAX_REQUIRED_RELATION_KWARG_VARIANTS = 32


class FieldType(TypedDict):
    type: Required[str]
    """The stringified type annotation to be used."""

    typing_imports: list[str]
    """A list of typing objects to be imported."""

    extra_imports: list[ImportItem]
    """A list of extra import items to be included."""


# This types are taken from `django-stubs`
# NOTE: Order matters! This dict is iterated in order to match field classes
# against the keys. Be sure to define the most specific subclasses first
# (e.g. `AutoField` is a subclass of `IntegerField`, so it is defined first).
# NOTE: Maybe `get_args(field_instance.__orig_class__)` could be used to take into
# account explicit parametrization.
FIELD_SET_TYPES_MAP: dict[type[Field], FieldType] = {
    AutoField: {
        "type": "int | str | Combinable",
    },
    IntegerField: {"type": "float | int | str | Combinable"},
    FloatField: {"type": "float | int | str | Combinable"},
    DecimalField: {"type": "str | float | Decimal | Combinable", "extra_imports": [ImportItem("decimal", "Decimal")]},
    CharField: {"type": "str | int | Combinable"},  # TODO this and textfield seems to allow `SupportsStr`
    TextField: {"type": "str | Combinable"},
    BooleanField: {"type": "bool | Combinable"},
    IPAddressField: {"type": "str | Combinable"},
    GenericIPAddressField: {
        "type": "str | int | Callable[..., Any] | Combinable",  # TODO, Callable, really?
        "typing_imports": ["Any", "Callable"],
    },
    # For datetime related fields, we use `datetime.x` because `datetime`
    # is already imported in `db/models/manager.pyi`:
    DateTimeField: {
        "type": "str | datetime.datetime | datetime.date | Combinable",
        "extra_imports": [ImportItem("datetime")],
    },
    DateField: {
        "type": "str | datetime.date | Combinable",
        "extra_imports": [ImportItem("datetime")],
    },
    TimeField: {
        "type": "str | datetime.time | datetime.datetime | Combinable",
        "extra_imports": [ImportItem("datetime")],
    },
    UUIDField: {"type": "str | UUID", "extra_imports": [ImportItem("uuid", "UUID")]},
    Field: {"type": "Any", "typing_imports": ["Any"]},
}
"""A mapping of field classes to the types they allow to be set to."""


class ModelCreationBaseCodemod(StubVisitorBasedCodemod, ABC):
    """A base codemod that can be used to add overloads for model creation.

    Useful for: `Model.__init__`, `Manager.create`.
    """

    METADATA_DEPENDENCIES = {ScopeProvider}
    KWARGS_TYPED_DICT_NAME: ClassVar[str]
    """A templated string to render the name of the `TypedDict` for the `**kwargs` annotation.

    Should contain the template `{model_name}`.
    """

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        self.add_model_imports()
        self.model_kwargs_names: dict[str, list[str]] = {}

        model_typed_dicts = self.build_model_kwargs()
        InsertAfterImportsVisitor.insert_after_imports(context, model_typed_dicts)

        AddImportsVisitor.add_needed_import(
            self.context,
            module="django.db.models.expressions",
            obj="Combinable",
        )

        # Even though most of them are likely included, we import them for safety:
        self.add_typing_imports(["TypedDict", "TypeVar", "Required", "Unpack", "overload"])

    def build_model_kwargs(self) -> list[cst.ClassDef]:
        """Return a list of class definition representing the typed dicts to be used for overloads."""

        generic_foreign_key_cls = None
        if self.django_context.apps.is_installed("django.contrib.contenttypes"):
            from django.contrib.contenttypes.fields import GenericForeignKey

            generic_foreign_key_cls = GenericForeignKey
        all_optional = self.stubs_settings.MODEL_FIELDS_OPTIONAL

        class_defs: list[cst.ClassDef] = []

        for model in self.django_context.models:
            model_name = self.django_context.get_model_name(model)

            # This mostly follows the implementation of the Django's `Model.__init__` method:
            attribute_options: list[list[list[TypedDictAttribute]]] = []
            for field in cast(list[Field], model._meta.fields):
                required = not all_optional and self.django_context.is_required_field(field)
                if isinstance(field.remote_field, ForeignObjectRel):
                    attr_name = field.name
                    if isinstance(field.remote_field.model, str):
                        # This seems to happen when a string reference can't be resolved
                        # It should be invalid at runtime but let's not error here.
                        annotation = "Any"
                        self.add_typing_imports(["Any"])
                    else:
                        annotation = self.django_context.get_model_name(
                            # As per `ForwardManyToOneDescriptor.__set__`:
                            field.remote_field.model._meta.concrete_model
                        )
                        annotation += " | Combinable"
                elif generic_foreign_key_cls is not None and isinstance(field, generic_foreign_key_cls):
                    # it's generic, so cannot set specific model
                    attr_name = field.name
                    annotation = "Any"
                    self.add_typing_imports(["Any"])
                else:
                    attr_name = field.attname
                    # Regular fields:
                    annotation = self.get_field_set_annotation(field)

                if (generic_foreign_key_cls is None or not isinstance(field, generic_foreign_key_cls)) and (
                    self.django_context.is_nullable_field(field)
                ):
                    annotation += " | None"

                attr = TypedDictAttribute(
                    attr_name,
                    annotation=annotation,
                    docstring=getattr(field, "help_text", None) or None,
                    required=required,
                )
                field_options = [[attr]]
                if (
                    isinstance(field.remote_field, ForeignObjectRel)
                    and field.attname != field.name
                    and not isinstance(field.remote_field.model, str)
                ):
                    attname_annotation = self.get_field_set_annotation(field.target_field)
                    if self.django_context.is_nullable_field(field):
                        attname_annotation += " | None"
                    attname_attr = TypedDictAttribute(
                        field.attname,
                        annotation=attname_annotation,
                        docstring=getattr(field, "help_text", None) or None,
                    )
                    if required:
                        field_options.append(
                            [
                                TypedDictAttribute(
                                    attr.name,
                                    annotation=attr.annotation,
                                    docstring=attr.docstring,
                                ),
                                TypedDictAttribute(
                                    attname_attr.name,
                                    annotation=attname_attr.annotation,
                                    docstring=attname_attr.docstring,
                                    required=True,
                                ),
                            ]
                        )
                    else:
                        field_options[0].append(attname_attr)
                attribute_options.append(field_options)

            kwargs_variants = self.build_kwargs_variants(model_name, attribute_options)
            self.model_kwargs_names[model_name] = [name for name, _ in kwargs_variants]
            for name, typed_dict_attributes in kwargs_variants:
                class_defs.append(
                    build_typed_dict(
                        name,
                        attributes=typed_dict_attributes,
                        total=False,
                        leading_line=True,
                    )
                )

        return class_defs

    def build_kwargs_variants(
        self,
        model_name: str,
        attribute_options: list[list[list[TypedDictAttribute]]],
    ) -> list[tuple[str, list[TypedDictAttribute]]]:
        variant_count = 1
        for field_options in attribute_options:
            variant_count *= len(field_options)
            if variant_count > MAX_REQUIRED_RELATION_KWARG_VARIANTS:
                return [
                    (
                        self.KWARGS_TYPED_DICT_NAME.format(model_name=model_name),
                        [attr for field_options in attribute_options for attr in field_options[0]],
                    )
                ]

        variants: list[tuple[str, list[TypedDictAttribute]]] = []
        for field_option_indexes in product(*(range(len(options)) for options in attribute_options)):
            required_attnames = [
                attr.name
                for index, field_options in zip(field_option_indexes, attribute_options)
                for attr in field_options[index]
                if attr.required and field_options[index] is not field_options[0]
            ]
            if required_attnames:
                suffix = "By" + "".join(to_pascal(name) for name in required_attnames)
                name = f"{self.KWARGS_TYPED_DICT_NAME.format(model_name=model_name)}{suffix}"
            else:
                name = self.KWARGS_TYPED_DICT_NAME.format(model_name=model_name)
            variants.append(
                (
                    name,
                    [
                        attr
                        for index, field_options in zip(field_option_indexes, attribute_options)
                        for attr in field_options[index]
                    ],
                )
            )
        return variants

    def get_field_set_annotation(self, field: Field) -> str:
        field_set_type = next(
            (v for k, v in FIELD_SET_TYPES_MAP.items() if issubclass(type(field), k)),
            FieldType(type="Any", typing_imports=["Any"]),
        )

        self.add_typing_imports(field_set_type.get("typing_imports", []))
        if extra_imports := field_set_type.get("extra_imports"):
            imports = AddImportsVisitor._get_imports_from_context(self.context)
            imports.extend(extra_imports)
            self.context.scratch[AddImportsVisitor.CONTEXT_KEY] = imports

        return field_set_type["type"]

    def mutate_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> FlattenFunctionDef:
        class_name = self.get_metadata(ScopeProvider, original_node).name

        overload = updated_node.with_changes(decorators=[OVERLOAD_DECORATOR])
        overloads: list[cst.FunctionDef] = []

        for model in self.django_context.models:
            model_name = self.django_context.get_model_name(model)

            # sets `self: BaseManager[model_name]/_QuerySet[model_name, _Row]/model_name`
            annotation = self.get_self_annotation(model_name, class_name)
            self_param = get_param(overload, "self")
            overload_ = overload.with_deep_changes(
                old_node=self_param,
                annotation=cst.Annotation(annotation),
            )

            for kwargs_name in self.model_kwargs_names[model_name]:
                overloads.append(
                    overload_.with_deep_changes(
                        old_node=overload_.params.star_kwarg,
                        annotation=cst.Annotation(
                            annotation=helpers.parse_template_expression(f"Unpack[{kwargs_name}]")
                        ),
                    )
                )

        # Keep a catch-all so type checkers that cannot match Unpack[TypedDict]
        # (notably ty) still accept Manager.create(**kwargs).
        overloads.append(updated_node.with_changes(decorators=[OVERLOAD_DECORATOR]))
        return cst.FlattenSentinel(overloads)

    @abstractmethod
    def get_self_annotation(self, model_name: str, class_name: str) -> cst.BaseExpression:
        """Return the annotation to be set on the `self` parameter."""
