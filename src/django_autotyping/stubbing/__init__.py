from __future__ import annotations

import importlib.metadata
import shutil
import site
import sys
from pathlib import Path

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext

from django_autotyping.app_settings import StubsGenerationSettings

from .codemods import StubVisitorBasedCodemod
from .django_context import DjangoStubbingContext
from .project_models import create_project_model_stubs as create_project_model_stubs

REQUIRED_DJANGO_STUB_FILES = frozenset(
    {
        "apps/registry.pyi",
        "conf/__init__.pyi",
        "contrib/auth/__init__.pyi",
        "db/models/base.pyi",
        "db/models/fields/related.pyi",
        "db/models/manager.pyi",
        "db/models/query.pyi",
        "template/loader.pyi",
        "test/testcases.pyi",
        "test/utils.pyi",
        "urls/base.pyi",
        "views/generic/detail.pyi",
        "views/generic/list.pyi",
    }
)


def run_codemods(
    codemods: list[type[StubVisitorBasedCodemod]],
    django_context: DjangoStubbingContext,
    stubs_settings: StubsGenerationSettings,
) -> None:
    django_stubs_dir = stubs_settings.SOURCE_STUBS_DIR or _get_django_stubs_dir()
    processed_stub_files: set[str] = set()

    for codemod in codemods:
        for stub_file in codemod.STUB_FILES:
            context = CodemodContext(
                filename=stub_file, scratch={"django_context": django_context, "stubs_settings": stubs_settings}
            )
            transformer = codemod(context)
            target_file = stubs_settings.LOCAL_STUBS_DIR / "django-stubs" / stub_file
            source_file = target_file if stub_file in processed_stub_files else django_stubs_dir / stub_file

            input_code = source_file.read_text(encoding="utf-8")
            input_module = cst.parse_module(input_code)
            output_module = transformer.transform_module(input_module)

            target_file.write_text(output_module.code, encoding="utf-8")
            processed_stub_files.add(stub_file)


def _get_django_stubs_dir() -> Path:
    try:
        distribution = importlib.metadata.distribution("django-stubs")
    except importlib.metadata.PackageNotFoundError:
        distribution = None
    if distribution is not None:
        candidate = Path(distribution.locate_file("django-stubs"))
        if _is_usable_django_stubs_dir(candidate):
            return candidate

    search_paths = [*site.getsitepackages(), site.getusersitepackages(), *sys.path]
    for path_entry in search_paths:
        if not path_entry:
            continue
        if (path := Path(path_entry, "django-stubs")).is_dir():
            if _is_usable_django_stubs_dir(path):
                return path
    raise RuntimeError("Couldn't find a usable 'django-stubs' package in any of the site packages.")


def _is_usable_django_stubs_dir(path: Path) -> bool:
    return path.is_dir() and all((path / stub_file).is_file() for stub_file in REQUIRED_DJANGO_STUB_FILES)


def create_local_django_stubs(stubs_dir: Path, source_django_stubs: Path | None = None) -> None:
    """Copy the `django-stubs` package into the specified local stubs directory.

    If `source_django_stubs` is not provided, the first entry in site packages will be used.
    """
    stubs_dir.mkdir(exist_ok=True)
    source_django_stubs = source_django_stubs or _get_django_stubs_dir()
    if not (stubs_dir / "django-stubs").is_dir():
        shutil.copytree(source_django_stubs, stubs_dir / "django-stubs")

    # for stub_file in django_stubs_dir.glob("**/*.pyi"):
    #     # Make file relative to site packages, results in `Path("django-stubs/path/to/file.pyi")`
    #     relative_stub_file = stub_file.relative_to(django_stubs_dir.parent)
    #     symlinked_path = stubs_dir / relative_stub_file

    #     stub_file.mkdir()


def create_local_rest_framework_stubs(stubs_dir: Path) -> None:
    """Create local overlays for Django REST Framework stubs."""
    try:
        distribution = importlib.metadata.distribution("djangorestframework-stubs")
    except importlib.metadata.PackageNotFoundError:
        return

    source_stubs = Path(distribution.locate_file("rest_framework-stubs"))
    if not source_stubs.is_dir():
        return

    target_package = stubs_dir / "rest_framework-stubs"
    if not target_package.is_dir():
        shutil.copytree(source_stubs, target_package)

    response_stub = target_package / "response.pyi"
    input_module = cst.parse_module(response_stub.read_text(encoding="utf-8"))
    output_module = input_module.visit(_DRFResponseStubTransformer())
    response_stub.write_text(output_module.code, encoding="utf-8")

    relations_stub = target_package / "relations.pyi"
    input_module = cst.parse_module(relations_stub.read_text(encoding="utf-8"))
    output_module = input_module.visit(_DRFRelationsStubTransformer())
    relations_stub.write_text(output_module.code, encoding="utf-8")


class _DRFResponseStubTransformer(cst.CSTTransformer):
    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if original_node.name.value != "_MonkeyPatchedResponse":
            return updated_node

        if any(
            m.matches(statement, m.SimpleStatementLine(body=[m.AnnAssign(target=m.Name("url"))]))
            for statement in updated_node.body.body
        ):
            return updated_node

        return updated_node.with_changes(
            body=updated_node.body.with_changes(
                body=[
                    cst.parse_statement("url: str\n"),
                    *updated_node.body.body,
                ],
            ),
        )


class _DRFRelationsStubTransformer(cst.CSTTransformer):
    def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
        if not m.matches(original_node.module, m.Name("typing")):
            return updated_node
        existing_names = {
            alias.name.value
            for alias in updated_node.names
            if isinstance(alias, cst.ImportAlias) and isinstance(alias.name, cst.Name)
        }
        needed_aliases = [
            cst.ImportAlias(name=cst.Name(name))
            for name in ("Literal", "overload")
            if name not in existing_names
        ]
        if not needed_aliases or not isinstance(updated_node.names, tuple):
            return updated_node
        return updated_node.with_changes(names=(*updated_node.names, *needed_aliases))

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if original_node.name.value != "RelatedField":
            return updated_node

        body: list[cst.BaseStatement] = []
        for statement in updated_node.body.body:
            if m.matches(statement, m.FunctionDef(name=m.Name("__new__"))):
                body.extend(
                    [
                        cst.parse_statement(
                            "@overload\n"
                            "def __new__(cls, *args: Any, many: Literal[True], **kwargs: Any) "
                            "-> ManyRelatedField: ...\n"
                        ),
                        cst.parse_statement(
                            "@overload\n"
                            "def __new__(cls, *args: Any, many: Literal[False] = ..., **kwargs: Any) -> Self: ...\n"
                        ),
                        cst.parse_statement(
                            "@overload\n"
                            "def __new__(cls, *args: Any, many: bool, **kwargs: Any) "
                            "-> Self | ManyRelatedField: ...\n"
                        ),
                    ]
                )
                continue
            body.append(statement)

        return updated_node.with_changes(body=updated_node.body.with_changes(body=body))
