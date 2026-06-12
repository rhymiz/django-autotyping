from __future__ import annotations

import ast
import importlib
import inspect
from collections import defaultdict
from pathlib import Path
from types import ModuleType

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.fields.reverse_related import ForeignObjectRel, ManyToManyRel, OneToOneRel

from django_autotyping.app_settings import StubsGenerationSettings
from django_autotyping.typing import ModelType

from .django_context import DjangoStubbingContext


class ImportPlanner:
    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}

    def annotation_for_model(self, model: ModelType, current_module: ModuleType) -> str:
        module = inspect.getmodule(model)
        if module is None or module.__name__ == current_module.__name__:
            return model.__name__
        alias = self._aliases.setdefault(module.__name__, f"_model_{len(self._aliases)}")
        return f"{alias}.{model.__name__}"

    def render_imports(self) -> list[str]:
        return [f"import {module_name} as {alias}" for module_name, alias in sorted(self._aliases.items())]


def create_project_model_stubs(
    django_context: DjangoStubbingContext,
    stubs_settings: StubsGenerationSettings,
) -> None:
    """Generate first-party ``models.pyi`` overlays for Django model modules."""

    if stubs_settings.MODEL_STUBS_DIR is None:
        return

    stubs_root = stubs_settings.MODEL_STUBS_DIR.resolve()
    source_root = (stubs_settings.MODEL_STUBS_SOURCE_DIR or stubs_settings.MODEL_STUBS_DIR).resolve()

    for module, module_models in _group_project_models(django_context, source_root).items():
        module_file = _module_file(module)
        if module_file is None:
            continue

        target_path = stubs_root / module_file.relative_to(source_root).with_suffix(".pyi")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(_render_module_stub(module, module_models, django_context), encoding="utf-8")


def _group_project_models(
    django_context: DjangoStubbingContext,
    source_root: Path,
) -> dict[ModuleType, list[ModelType]]:
    grouped: dict[ModuleType, list[ModelType]] = defaultdict(list)

    for model in django_context.models:
        module = inspect.getmodule(model)
        module_file = _module_file(module)
        if module is not None and module_file is not None and _is_relative_to(module_file, source_root):
            grouped[module].append(model)

    for module in list(grouped):
        for model in _model_classes_in_module(module):
            if model not in grouped[module]:
                grouped[module].append(model)

    return dict(grouped)


def _module_file(module: ModuleType | None) -> Path | None:
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        return None
    path = Path(module_file).resolve()
    if path.suffix != ".py":
        return None
    return path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _model_classes_in_module(module: ModuleType) -> list[ModelType]:
    classes: list[ModelType] = []
    for value in vars(module).values():
        if inspect.isclass(value) and issubclass(value, models.Model) and value.__module__ == module.__name__:
            classes.append(value)
    return classes


def _render_module_stub(
    module: ModuleType,
    module_models: list[ModelType],
    django_context: DjangoStubbingContext,
) -> str:
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    planner = ImportPlanner()
    model_by_name = {model.__name__: model for model in module_models}

    body: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            model = model_by_name.get(node.name)
            if model is not None:
                body.extend(_render_model_class(node, model, module, planner))
            else:
                body.extend(_render_plain_class(node, module))
        elif isinstance(node, ast.FunctionDef):
            body.append(_render_function(node))
        elif isinstance(node, ast.Assign):
            body.extend(_render_assignments(node, module))

    imports = [
        "from __future__ import annotations",
        "",
        "import datetime",
        "import decimal",
        "from typing import Any, ClassVar",
        "from uuid import UUID",
        "",
        "from django.db import models",
        "from django.db.models.manager import BaseManager, ManyToManyRelatedManager, RelatedManager",
        *planner.render_imports(),
        "",
    ]

    return "\n".join(imports + body).rstrip() + "\n"


def _render_model_class(
    node: ast.ClassDef,
    model: ModelType,
    module: ModuleType,
    planner: ImportPlanner,
) -> list[str]:
    class_name = model.__name__
    lines = [f"class {class_name}(models.Model):"]
    members: list[str] = [
        f"objects: ClassVar[BaseManager[{class_name}]]",
        f"_default_manager: ClassVar[BaseManager[{class_name}]]",
        f"_base_manager: ClassVar[BaseManager[{class_name}]]",
    ]

    for manager in model._meta.managers:
        members.append(f"{manager.name}: ClassVar[BaseManager[{class_name}]]")

    pk = model._meta.pk
    if pk is not None:
        members.append(f"pk: {_field_value_type(pk, module, planner)}")

    for field in model._meta.fields:
        members.extend(_render_field_attributes(field, module, planner))

    for field in model._meta.many_to_many:
        members.append(
            f"{field.name}: "
            f"{_many_to_many_manager_type(field.remote_field.through, field.remote_field.model, module, planner)}"
        )

    for name, value in vars(model).items():
        if _is_generic_foreign_key(value):
            members.append(f"{name}: Any")

    for relation in model._meta.related_objects:
        accessor_name = relation.get_accessor_name()
        if not accessor_name or accessor_name == "+":
            continue
        annotation = _reverse_relation_type(relation, module, planner)
        if annotation is not None:
            members.append(f"{accessor_name}: {annotation}")

    members.extend(_render_inner_classes(node))
    members.extend(_render_methods(node))

    lines.extend(_indent_lines(_dedupe(members)) or ["    ..."])
    lines.append("")
    return lines


def _render_field_attributes(field: models.Field, module: ModuleType, planner: ImportPlanner) -> list[str]:
    if isinstance(field.remote_field, ForeignObjectRel) and not isinstance(field.remote_field.model, str):
        annotation = planner.annotation_for_model(field.remote_field.model._meta.concrete_model, module)
        if field.null:
            annotation = f"{annotation} | None"
        id_annotation = _field_value_type(field.target_field, module, planner)
        if field.null:
            id_annotation = f"{id_annotation} | None"
        return [f"{field.name}: {annotation}", f"{field.attname}: {id_annotation}"]

    annotation = _field_value_type(field, module, planner)
    if field.null:
        annotation = f"{annotation} | None"
    return [f"{field.attname}: {annotation}"]


def _field_value_type(field: models.Field, module: ModuleType, planner: ImportPlanner) -> str:
    if isinstance(field, (models.ForeignKey, models.OneToOneField)) and not isinstance(field.remote_field.model, str):
        return planner.annotation_for_model(field.remote_field.model._meta.concrete_model, module)

    field_type_map: tuple[tuple[tuple[type[models.Field], ...], str], ...] = (
        ((models.AutoField, models.BigAutoField, models.SmallAutoField), "int"),
        (
            (
                models.IntegerField,
                models.BigIntegerField,
                models.SmallIntegerField,
                models.PositiveIntegerField,
                models.PositiveBigIntegerField,
                models.PositiveSmallIntegerField,
            ),
            "int",
        ),
        ((models.UUIDField,), "UUID"),
        ((models.BooleanField,), "bool"),
        ((models.FloatField,), "float"),
        ((models.DecimalField,), "decimal.Decimal"),
        ((models.DateTimeField,), "datetime.datetime"),
        ((models.DateField,), "datetime.date"),
        ((models.TimeField,), "datetime.time"),
        ((models.DurationField,), "datetime.timedelta"),
        ((models.BinaryField,), "bytes"),
        ((models.JSONField, models.FileField), "Any"),
    )
    for field_classes, annotation in field_type_map:
        if isinstance(field, field_classes):
            return annotation
    return "str" if isinstance(field, models.Field) else "Any"


def _reverse_relation_type(
    relation: ForeignObjectRel,
    module: ModuleType,
    planner: ImportPlanner,
) -> str | None:
    related_model = relation.related_model
    if isinstance(related_model, str):
        return None
    related_annotation = planner.annotation_for_model(related_model, module)
    if isinstance(relation, OneToOneRel):
        return related_annotation
    if isinstance(relation, ManyToManyRel):
        return _many_to_many_manager_type(relation.through, related_model, module, planner)
    return f"RelatedManager[{related_annotation}]"


def _many_to_many_manager_type(
    through_model: ModelType,
    related_model: ModelType | str,
    module: ModuleType,
    planner: ImportPlanner,
) -> str:
    related_annotation = (
        "Any" if isinstance(related_model, str) else planner.annotation_for_model(related_model, module)
    )
    through_annotation = planner.annotation_for_model(through_model, module)
    return f"ManyToManyRelatedManager[{related_annotation}, {through_annotation}]"


def _is_generic_foreign_key(value: object) -> bool:
    try:
        fields_module = importlib.import_module("django.contrib.contenttypes.fields")
    except (ImportError, ImproperlyConfigured):
        return False
    generic_foreign_key = fields_module.GenericForeignKey
    if not isinstance(generic_foreign_key, type):
        return False
    return isinstance(value, generic_foreign_key)


def _render_plain_class(node: ast.ClassDef, module: ModuleType) -> list[str]:
    value = getattr(module, node.name, None)
    if inspect.isclass(value) and issubclass(value, models.TextChoices):
        base = "models.TextChoices"
        members = _choice_members(node, annotation="models.TextChoices")
    elif inspect.isclass(value) and issubclass(value, models.IntegerChoices):
        base = "models.IntegerChoices"
        members = _choice_members(node, annotation="models.IntegerChoices")
    elif inspect.isclass(value) and issubclass(value, models.Manager):
        base = "models.Manager[Any]"
        members = _render_methods(node)
    else:
        base = "object"
        members = _render_methods(node)

    lines = [f"class {node.name}({base}):"]
    lines.extend(_indent_lines(members) or ["    ..."])
    lines.append("")
    return lines


def _render_inner_classes(node: ast.ClassDef) -> list[str]:
    rendered: list[str] = []
    for child in node.body:
        if not isinstance(child, ast.ClassDef):
            continue
        if child.name == "Meta":
            rendered.extend(["class Meta:", "    ...", ""])
        elif _class_uses_base(child, "TextChoices"):
            rendered.extend(
                [
                    f"class {child.name}(models.TextChoices):",
                    *_indent_lines(_choice_members(child, annotation="models.TextChoices")),
                    "",
                ]
            )
        elif _class_uses_base(child, "IntegerChoices"):
            rendered.extend(
                [
                    f"class {child.name}(models.IntegerChoices):",
                    *_indent_lines(_choice_members(child, annotation="models.IntegerChoices")),
                    "",
                ]
            )
    return rendered


def _choice_members(node: ast.ClassDef, *, annotation: str) -> list[str]:
    members: list[str] = []
    for child in node.body:
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    members.append(f"{target.id}: {annotation}")
    return members or ["..."]


def _render_methods(node: ast.ClassDef) -> list[str]:
    members: list[str] = []
    for child in node.body:
        if not isinstance(child, ast.FunctionDef):
            continue
        if child.name == "__init__":
            continue
        if _has_decorator(child, "property"):
            members.append(f"{child.name}: Any")
            continue
        return_type = "str" if child.name == "__str__" else "Any"
        members.append(f"def {child.name}(self, *args: Any, **kwargs: Any) -> {return_type}: ...")
    return members


def _render_function(node: ast.FunctionDef) -> str:
    return f"def {node.name}(*args: Any, **kwargs: Any) -> Any: ..."


def _render_assignments(node: ast.Assign, module: ModuleType) -> list[str]:
    lines: list[str] = []
    for target in node.targets:
        if not isinstance(target, ast.Name):
            continue
        value = getattr(module, target.id, None)
        if inspect.isclass(value) and issubclass(value, models.Model):
            lines.append(f"{target.id}: type[models.Model]")
        elif target.id.isupper() or target.id.endswith("_model"):
            lines.append(f"{target.id}: Any")
    return lines


def _annotation_to_string(annotation: ast.expr | None) -> str:
    if annotation is None:
        return "Any"
    try:
        return ast.unparse(annotation)
    except Exception:
        return "Any"


def _class_uses_base(node: ast.ClassDef, base_name: str) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == base_name:
            return True
        if isinstance(base, ast.Attribute) and base.attr == base_name:
            return True
    return False


def _has_decorator(node: ast.FunctionDef, decorator_name: str) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == decorator_name:
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == decorator_name:
            return True
    return False


def _indent_lines(lines: list[str]) -> list[str]:
    return [f"    {line}" if line else "" for line in lines]


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped
