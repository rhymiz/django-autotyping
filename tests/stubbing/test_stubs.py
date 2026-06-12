# ruff: noqa: E501
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest
from mypy.api import run as run_mypy
from pyright import main as run_pyright

from django_autotyping.app_settings import StubsGenerationSettings
from django_autotyping.stubbing import create_local_django_stubs, create_project_model_stubs, run_codemods
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


def test_project_model_stubs_include_dynamic_model_attrs(tmp_path, stubstestproj_context):
    stubs_settings = StubsGenerationSettings(MODEL_STUBS_DIR=tmp_path, MODEL_STUBS_SOURCE_DIR=STUBSTESTPROJ)

    create_project_model_stubs(stubstestproj_context, stubs_settings)

    firstapp_models = tmp_path / "firstapp" / "models.pyi"
    secondapp_models = tmp_path / "secondapp" / "models.pyi"

    assert firstapp_models.exists()
    assert secondapp_models.exists()

    firstapp = firstapp_models.read_text()
    secondapp = secondapp_models.read_text()

    assert "model_two: _model_" in firstapp
    assert "model_two_id: int" in firstapp
    assert "many_to_many_model_two: ManyToManyRelatedManager[" in firstapp
    assert "def default_zone(*args: Any, **kwargs: Any) -> Any: ..." in firstapp
    assert "class Meta:" in firstapp
    assert "DRAFT: models.TextChoices" in firstapp
    assert "tzinfo: Any" in firstapp
    assert "def related_zone(self, *args: Any, **kwargs: Any) -> Any: ..." in firstapp
    assert "ZoneInfo" not in firstapp
    assert "modelone_set: RelatedManager[" in secondapp


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
