# Contributing

Thanks for helping improve streamgrab.

## Development setup

```bash
git clone https://github.com/yourname/streamgrab
cd streamgrab
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,crypto]"
```

If your system blocks global installs (PEP 668), use `uv`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev,crypto]"
```

## Running tests

```bash
python -m pytest -q
```

Tests use only the standard library plus `pytest`. Network access is not
required: integration tests start a local `http.server` and serve generated
fixtures.

## Style

```bash
ruff check streamgrab tests
```

Keep the public API small, prefer standard library, and add a test for every
behavior change. New extractors should include a parsing unit test with a
captured (or synthetic) sample.

## Adding an extractor

1. Create a class subclassing `streamgrab.extractor.Extractor`.
2. Implement `matches` and `extract`.
3. Choose a `priority` (higher runs first; keep generic fallbacks negative).
4. Add it to `default_extractors()` or ship it as a plugin.
5. Add tests.

## Pull requests

- One logical change per PR.
- Describe the behavior change and how you tested it.
- Do not add site-specific credential bypasses or DRM circumvention.

By contributing you agree your contributions are licensed under the MIT License.
