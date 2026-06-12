# ruff: noqa: E501
from __future__ import annotations

import dataclasses
import importlib.metadata
import json
import os
from pathlib import Path

import pytest
from mypy.api import run as run_mypy
from pyright import main as run_pyright

from django_autotyping.app_settings import StubsGenerationSettings
from django_autotyping.stubbing import (
    create_local_django_stubs,
    create_local_rest_framework_stubs,
    create_project_model_stubs,
    run_codemods,
)
from django_autotyping.stubbing.codemods import gather_codemods

TESTFILES = Path(__file__).parent / "testfiles"
STUBSTESTPROJ = Path(__file__).parents[1].joinpath("stubstestproj").absolute()

# fmt: off
testfiles_params = pytest.mark.parametrize(
    ["testfile", "rules", "stubs_settings"],
    [
        ("djas001.py", ["DJAS001"], StubsGenerationSettings()),
        ("djas001_no_plain_references.py", ["DJAS001"], StubsGenerationSettings(ALLOW_PLAIN_MODEL_REFERENCES=False)),
        ("djas001_allow_non_set_type.py", ["DJAS001"], StubsGenerationSettings(ALLOW_NONE_SET_TYPE=True)),
        ("djas002_003.py", ["DJAS002", "DJAS003"], StubsGenerationSettings()),
        ("djas002_003_no_model_fields_optional.py", ["DJAS002", "DJAS003"], StubsGenerationSettings(MODEL_FIELDS_OPTIONAL=False)),
        ("djas010.py", ["DJAS010"], StubsGenerationSettings()),
        ("djas011.py", ["DJAS011"], StubsGenerationSettings()),
        ("djas015.py", ["DJAS015"], StubsGenerationSettings()),
        ("djas016.py", ["DJAS016"], StubsGenerationSettings()),
        ("djas017.py", ["DJAS017"], StubsGenerationSettings()),
    ],
)
# fmt: on


@pytest.fixture
def local_stubs(tmp_path) -> Path:
    create_local_django_stubs(tmp_path)
    return tmp_path


def test_model_init_kwargs_are_generated_once(local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(LOCAL_STUBS_DIR=local_stubs)

    codemods = gather_codemods(include=["DJAS003"])
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    base_stubs = local_stubs / "django-stubs" / "db" / "models" / "base.pyi"

    assert base_stubs.read_text().count("class ModelOneInitKwargs(TypedDict, total=False):") == 1


def test_reverse_overloads_preserve_dynamic_str_fallback(local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(LOCAL_STUBS_DIR=local_stubs)

    codemods = gather_codemods(include=["DJAS015"])
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    base_stubs = local_stubs / "django-stubs" / "urls" / "base.pyi"
    generated = base_stubs.read_text()

    assert "viewname: Callable[..., HttpResponseBase] | str | None," in generated
    assert 'viewname: Literal["item-detail"],' in generated
    assert (
        "kwargs: _24DFE8Kwargs | _2AD99CKwargs," in generated
        or "kwargs: _2AD99CKwargs | _24DFE8Kwargs," in generated
    )


def test_drf_test_client_stub_is_opt_in(local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(LOCAL_STUBS_DIR=local_stubs, DRF_TEST_CLIENT=True)

    codemods = gather_codemods(include=["DJAS018"])
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    testcases_stubs = local_stubs / "django-stubs" / "test" / "testcases.pyi"
    generated = testcases_stubs.read_text()

    assert "from rest_framework.test import APIClient" in generated
    assert "client_class: type[APIClient]" in generated
    assert "client: APIClient" in generated


def test_context_list_supports_string_lookup(local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(LOCAL_STUBS_DIR=local_stubs)

    codemods = gather_codemods(include=["DJAS019"])
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    utils_stubs = local_stubs / "django-stubs" / "test" / "utils.pyi"
    generated = utils_stubs.read_text()

    upstream_fixed_getitem = "def __getitem__(self, key: str | SupportsIndex | slice) -> Any: ..." in generated
    generated_getitem_overloads = all(
        overload in generated
        for overload in [
            "def __getitem__(self, key: str) -> _T: ...",
            "def __getitem__(self, key: int) -> Mapping[str, _T]: ...",
            "def __getitem__(self, key: slice) -> list[Mapping[str, _T]]: ...",
        ]
    )
    assert upstream_fixed_getitem or generated_getitem_overloads


def test_testcase_capture_on_commit_callbacks(local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(LOCAL_STUBS_DIR=local_stubs)

    codemods = gather_codemods(include=["DJAS020"])
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    testcases_stubs = local_stubs / "django-stubs" / "test" / "testcases.pyi"
    generated = testcases_stubs.read_text()

    assert "from contextlib import AbstractContextManager" in generated
    assert "from django.forms.forms import BaseForm" in generated
    assert "def captureOnCommitCallbacks(" in generated
    assert "AbstractContextManager[list[Callable[[], None]]]" in generated
    assert "form: BaseForm" in generated
    assert "response: HttpResponse,\n        form: str," not in generated


def test_testcase_codemods_are_cumulative(local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(LOCAL_STUBS_DIR=local_stubs, DRF_TEST_CLIENT=True)

    codemods = gather_codemods(include=["DJAS018", "DJAS020"])
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    testcases_stubs = local_stubs / "django-stubs" / "test" / "testcases.pyi"
    generated = testcases_stubs.read_text()

    assert "client: APIClient" in generated
    assert "def captureOnCommitCallbacks(" in generated


def test_generic_view_runtime_attrs(local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(LOCAL_STUBS_DIR=local_stubs)

    codemods = gather_codemods(include=["DJAS021"])
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    detail_stubs = local_stubs / "django-stubs" / "views" / "generic" / "detail.pyi"
    list_stubs = local_stubs / "django-stubs" / "views" / "generic" / "list.pyi"

    assert "    object: models.Model\n" in detail_stubs.read_text()
    assert "    object_list: _BaseQuerySet[Any]\n" in list_stubs.read_text()


def test_rest_framework_response_overlay_adds_redirect_url(tmp_path):
    try:
        importlib.metadata.distribution("djangorestframework-stubs")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("djangorestframework-stubs is not installed")

    create_local_rest_framework_stubs(tmp_path)

    response_stubs = tmp_path / "rest_framework-stubs" / "response.pyi"
    relations_stubs = tmp_path / "rest_framework-stubs" / "relations.pyi"
    generated = response_stubs.read_text()
    generated_relations = relations_stubs.read_text()

    assert (tmp_path / "rest_framework-stubs" / "__init__.pyi").exists()
    assert "class _MonkeyPatchedResponse(Response):\n    url: str" in generated
    assert "from typing import Any, TypeVar, Literal, overload" in generated_relations
    assert "many: Literal[True]" in generated_relations
    assert "many: Literal[False] = ..." in generated_relations
    assert "-> Self | ManyRelatedField" in generated_relations


def test_project_model_stubs_include_dynamic_model_attrs(tmp_path, local_stubs, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(
        LOCAL_STUBS_DIR=local_stubs,
        MODEL_STUBS_DIR=tmp_path,
        MODEL_STUBS_SOURCE_DIR=STUBSTESTPROJ,
    )

    create_project_model_stubs(stubstestproj_context, stubs_settings)

    firstapp_models = tmp_path / "firstapp" / "models.pyi"
    secondapp_models = tmp_path / "secondapp" / "models.pyi"
    auth_models = local_stubs / "django-stubs" / "contrib" / "auth" / "models.pyi"
    model_base = local_stubs / "django-stubs" / "db" / "models" / "base.pyi"

    assert firstapp_models.exists()
    assert secondapp_models.exists()
    assert auth_models.exists()

    firstapp = firstapp_models.read_text()
    secondapp = secondapp_models.read_text()
    auth = auth_models.read_text()
    base = model_base.read_text()

    assert "model_two: _model_" in firstapp
    assert "model_two_id: int" in firstapp
    assert "many_to_many_model_two: ManyToManyRelatedManager[" in firstapp
    assert "def default_zone(*args: Any, **kwargs: Any) -> Any: ..." in firstapp
    assert "class Meta:" in firstapp
    assert "DRAFT: models.TextChoices" in firstapp
    assert "tzinfo: Any" in firstapp
    assert "def related_zone(self, *args: Any, **kwargs: Any) -> Any: ..." in firstapp
    assert "ZoneInfo" not in firstapp
    assert "content_object: Any" in firstapp
    assert "modelone_set: RelatedManager[" in secondapp
    assert "class Group(models.Model):\n    generic_targets: RelatedManager[" in auth
    assert "# django-autotyping project model attrs start" in base
    assert "from stubstestproj.firstapp.models import ModelOne" in base
    assert "def __getattr__(self: ModelOne, name: Literal[" in base
    assert "def __getattr__(self: Model, name: Literal[" in base
    assert '"model_two_id"' in base
    assert '"model_two_nullable_id"' in base
    assert '"modelone_set"' in base
    assert '"many_to_many_model_two"' in base
    assert '"content_object"' in base
    assert "-> int | None: ..." in base
    assert "-> RelatedManager[Any]: ..." in base
    assert "-> ManyToManyRelatedManager[Any, Any]: ..." in base

    create_project_model_stubs(stubstestproj_context, stubs_settings)
    assert model_base.read_text().count("# django-autotyping project model attrs start") == 1


@pytest.mark.xfail(reason="mypy does not support setting the MYPYPATH without specifying a module or package to test.")
@pytest.mark.mypy
@testfiles_params
def test_mypy(
    monkeypatch,
    local_stubs,
    stubstestproj_context,
    # testfiles_params:
    testfile: Path,
    rules: list[str],
    stubs_settings: StubsGenerationSettings,
):
    testfile = TESTFILES / testfile
    stubs_settings = dataclasses.replace(stubs_settings, LOCAL_STUBS_DIR=local_stubs)

    codemods = gather_codemods(include=rules)
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    # TODO this does not work for now: https://github.com/python/mypy/issues/16775
    monkeypatch.setenv("MYPYPATH", os.pathsep.join(map(str, [local_stubs.absolute(), STUBSTESTPROJ])))

    _, _, exit_code = run_mypy([str(testfile.absolute())])

    assert exit_code == 0


@pytest.mark.pyright
@testfiles_params
def test_pyright(
    tmp_path,
    local_stubs,
    stubstestproj_context,
    # testfiles_params:
    testfile: Path,
    rules: list[str],
    stubs_settings: StubsGenerationSettings,
):
    testfile = TESTFILES / testfile
    stubs_settings = dataclasses.replace(stubs_settings, LOCAL_STUBS_DIR=local_stubs)

    codemods = gather_codemods(include=rules)
    run_codemods(codemods, stubstestproj_context, stubs_settings)

    config_file = tmp_path / "pyrightconfig.json"
    config_file.write_text(
        json.dumps(
            {
                "stubPath": str(local_stubs.absolute()),
                "extraPaths": [str(STUBSTESTPROJ.parent)],
                "reportUnnecessaryTypeIgnoreComment": True,
                "reportDeprecated": True,
            }
        )
    )

    exit_code = run_pyright(["--project", str(config_file), str(testfile)])

    assert exit_code == 0
