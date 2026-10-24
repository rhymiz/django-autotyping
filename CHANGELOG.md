# Changelog

## Unreleased

- Preserve PostgreSQL ArrayField element types, nesting and nullability in project
  model attributes and model/manager creation arguments. PostgreSQL drivers remain
  optional for projects that do not use PostgreSQL fields.
- Support Django 6.1: `GenericForeignKey` attributes are again included in project
  model stubs now that Django installs a descriptor on the model class.
- Test against every supported Django series (5.2 LTS, 6.0, 6.1) on Python 3.11–3.14.
- Drop Python 3.10 support (end of life since October 2026).
- Drop settings removed before Django 5.2 (`CSRF_COOKIE_MASKED`, `DEFAULT_FILE_STORAGE`,
  `STATICFILES_STORAGE`, `USE_DEPRECATED_PYTZ`, `USE_L10N`) from the settings stubs, and stop
  emitting `FORMS_URLFIELD_ASSUME_HTTPS` on Django 6.0+, where it was removed.
- Add settings introduced in Django 5.2–6.1: `MAILERS`, `SECURE_CSP`, `SECURE_CSP_REPORT_ONLY`,
  `SIGNED_COOKIE_LEGACY_SALT_FALLBACK` (security backport in 5.2.15/6.0.6), `TASKS`,
  `URLIZE_ASSUME_HTTPS` and `USE_BLANK_CHOICE_DASH`. Mark the `EMAIL_*` settings superseded by
  `MAILERS` as deprecated on Django 6.1.
- Fix settings stubs generation crashing for deprecated settings with non-identifier types,
  type `EMAIL_PORT` as `int`, and stop emitting `MESSAGE_LEVEL`/`MESSAGE_TAGS` unless configured.

## 0.5.1 (2024-05-29)

This release fixes two bugs:

- Fallback to `inspect.getmodule` for models not exported in the app's models module (#66)
- Fix type representation of `DateTimeField.__set__` types (#67)

## 0.5.0 (2024-02-18)

This release brings basic support for template loading functions (e.g. `render_to_string`).

- Fixed some typos in readme and docstrings (#50)
- Fixes and tests for `DJAS002/3` (#53)
- Add support for template loading functions (#56)
- Remove outdated VSCode limitation in docs (#57)

## 0.4.0 (2024-02-04)

This release brings improvements to the model creation related comemod:
- `DJAS002` was refactored and now provides better types for fields (instead of `Any`).
  It is now split into two rules: `DJAS002` and `DJAS003`.

- Fix README rendering for PyPI (#43)
- Add draft implementation for `call_command` overloads (#45)
- Refactor and improve support for model creation (#46)
- Update to `ruff==0.2.0`, add new rules (#47)
- Typos and updates to docs (#48)

## 0.3.0 (2024-01-23)

- Add more tests for DJAS001, test DJAS010 (#34)
- Add support for custom user model (#35)
- Add animated example (#38)
- Add support for settings typing (#37)

## 0.2.0 (2024-01-15)

- Complete refactor of the library (no post migrate signal, management commands)
- Added tests, docs

## 0.1.0 (2023-12-17)

- Add support for custom dynamic stubs
- Support duplicate models across apps
- Various improvements to the codebase

## 0.0.1 (2023-12-05)

- Initial release
