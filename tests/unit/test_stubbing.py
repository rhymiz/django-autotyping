import importlib
from pathlib import Path

from django.conf import settings

from django_autotyping.app_settings import StubsGenerationSettings
from django_autotyping.codemodding.codemods.base import BaseVisitorBasedCodemod
from django_autotyping.stubbing import _get_django_stubs_dir
from django_autotyping.stubbing.codemods.base import StubVisitorBasedCodemod


class Distribution:
    def __init__(self, root: Path) -> None:
        self.root = root

    def locate_file(self, path: str) -> Path:
        return self.root / path


def get_generate_stubs_module():
    if not settings.configured:
        settings.configure(AUTOTYPING={}, INSTALLED_APPS=[])
    return importlib.import_module("django_autotyping.management.commands.generate_stubs")


def test_get_django_stubs_dir_uses_distribution_metadata(monkeypatch, tmp_path):
    django_stubs = tmp_path / "django-stubs"
    django_stubs.mkdir()

    monkeypatch.setattr(
        "django_autotyping.stubbing.importlib.metadata.distribution",
        lambda name: Distribution(tmp_path),
    )

    assert _get_django_stubs_dir() == django_stubs


def test_visitor_based_codemods_define_libcst_metadata_provider_attr():
    assert BaseVisitorBasedCodemod.__provides__ is None
    assert StubVisitorBasedCodemod.__provides__ is None


def test_generate_stubs_uses_cli_local_stubs_dir(monkeypatch, tmp_path):
    generate_stubs = get_generate_stubs_module()
    source_stubs_dir = tmp_path / "source"
    local_stubs_dir = tmp_path / "local"
    source_stubs_dir.mkdir()
    local_stubs_dir.mkdir()
    captured = {}

    monkeypatch.setattr(
        generate_stubs,
        "stubs_settings",
        StubsGenerationSettings(SOURCE_STUBS_DIR=source_stubs_dir, LOCAL_STUBS_DIR=tmp_path / "settings"),
    )
    monkeypatch.setattr(
        generate_stubs,
        "create_local_django_stubs",
        lambda local, source=None: captured.update(create=(local, source)),
    )
    monkeypatch.setattr(generate_stubs, "gather_codemods", lambda ignore: ["codemod"])
    monkeypatch.setattr(generate_stubs, "DjangoStubbingContext", lambda apps, settings: "context")
    monkeypatch.setattr(
        generate_stubs,
        "run_codemods",
        lambda codemods, context, settings: captured.update(run=(codemods, context, settings)),
    )

    generate_stubs.Command().handle(local_stubs_dir=local_stubs_dir, ignore=[])

    assert captured["create"] == (local_stubs_dir, source_stubs_dir)
    assert captured["run"][0] == ["codemod"]
    assert captured["run"][1] == "context"
    assert captured["run"][2].LOCAL_STUBS_DIR == local_stubs_dir
    assert captured["run"][2].SOURCE_STUBS_DIR == source_stubs_dir
