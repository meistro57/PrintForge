# Installing PrintForge

PrintForge is a Python (>= 3.11) package. Rendering uses
[WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/), which needs a few
**native libraries** (Pango, HarfBuzz) in addition to its Python wheels.

## 1. Native prerequisites (Linux)

Debian / Ubuntu (including WSL2 Ubuntu):

```sh
sudo apt-get update
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core
```

Fedora:

```sh
sudo dnf install pango harfbuzz dejavu-serif-fonts dejavu-sans-mono-fonts
```

- `libpango-1.0-0` / `libpangoft2-1.0-0`: text layout (Pango >= 1.44 required by WeasyPrint).
- `libharfbuzz-subset0`: font subsetting for embedded fonts. Without it WeasyPrint still
  works but emits a `DeprecationWarning` and embeds larger fonts.
- `fonts-dejavu-core`: the default body/monospace fonts used by PrintForge's layout
  presets. Fonts are selected by family name and the rendered PDF is checked for the
  fonts actually embedded, so a missing font fails the build instead of silently
  substituting.

No network access is needed at build time; PrintForge never fetches remote assets.

## 2. Python package

```sh
git clone https://github.com/meistro57/PrintForge.git
cd PrintForge
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
printforge --help
```

## 3. Verify

```sh
ruff check . && ruff format --check .
pytest
```

`tests/test_stack.py` renders a one-page PDF with WeasyPrint and reads it back with
pypdf; if it fails with `OSError: cannot load library 'pango-1.0-0'` the native
libraries from step 1 are missing.
