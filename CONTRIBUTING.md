# Contributing to tray4hermes

Thanks for stopping by — every README PR or issue means somebody
care enough about a corner case to dig in.

## Quick start

```bash
git clone https://github.com/MoDD0/tray4hermes.git
cd tray4hermes
uv pip install --system -e ".[dev]"
./scripts/dev.sh            # install + run tests
```

Make a change, push, open a PR.

## Ground rules (flexible, but real)

1. **Don't break the tests.** The whole suite must stay green;
   `./scripts/dev.sh` runs it. (No fixed test count is quoted anywhere
   on purpose — a number in prose goes stale the first time somebody
   adds a test.)
2. **Don't add new runtime dependencies** without discussion — the
   package has one runtime dep (`PyQt5`), and we want to keep it
   that way.
3. **No secrets in the diff.**
   `grep -rE "sk-[a-z0-9]{16,}|api_key.*[a-z0-9]{20,}"` should be empty.
4. **No writes to `~/.hermes/*`** from inside the tray — that area
   is owned by Hermes Agent.
5. **MIT-compatible contributions.** Same license as the project.
6. **User-visible changes update documentation in the same commit.** Edit
   `docs/i18n/en.md` — it is the single source of truth — then bring
   `docs/i18n/cs.md` in line with it as a *translation of the new text*,
   never as a document that evolves on its own. Finally run
   `python scripts/i18n_build.py` to regenerate `README.md` and
   `docs/README.cs.md`, and commit sources and generated files together.

## Translations: two separate things

tray4hermes is translated in two independent places, and a new language
usually means touching only one of them:

| What | Lives in | Shipped as |
|---|---|---|
| **README / docs prose** | `docs/i18n/<lang>.md` | `README.md`, `docs/README.<lang>.md` |
| **UI strings** (menu, dialogs, tooltips) | `src/tray4hermes/_locales/<lang>/LC_MESSAGES/` | `gettext` catalogs inside the wheel |

Both currently cover **English (canonical)** and **Czech**. The two
sections below describe each route.

## Adding a README translation

Follow these conventions so the build tools stay sane and the language
picker stays in sync.

### File conventions

| Item | Convention | Example |
|------|-----------|---------|
| Source filename | `docs/i18n/<iso639-1>.md` | `docs/i18n/de.md` |
| Compiled output (canonical only) | `README.md` | n/a — already done for `en.md` |
| Compiled output (others) | `docs/README.<iso639-1>.md` | `docs/README.de.md` |
| Locale code | ISO 639-1 (two-letter) or ISO 639-3 fallback | `de`, `cs`, `zh-Hans`, … |
| Native name shown in banner | Self-referential in the language | `Deutsch`, `Čeština`, `简体中文` |

We use ISO 639-1 because GitHub's URL-language selectors (`?lang=…`)
recognise only that; the canonical exception is `zh-Hans` /
`zh-Hant` (BCP 47 extended) and `pt-BR` (regional variants) — both
are fine.

### Steps

1. **Copy `docs/i18n/en.md` to your locale file:** `cp
   docs/i18n/en.md docs/i18n/de.md`.

2. **Translate the prose.** Keep section structure (## headings)
   identical to the canonical. You don't have to translate
   technical terms in code spans — those are verbatim:
   - `systemd`, `DBus`, `SNI`, `PyQt5`, `JSON`, etc. stay as-is
   - Filenames, function names, error output, etc. stay verbatim

3. **Keep the i18n comment marker intact.** Don't edit the
   `<!-- i18n:available-languages:START --> … END -->` block —
   it's auto-generated. (See "How the build works" below.)

4. **Edit `scripts/i18n_build.py`** to register your locale.
   In `_LOCALES`, add an entry:
   ```python
   _LOCALES: list[tuple[str, str, str]] = [
       ("en", "English", "English"),
       ("cs", "Čeština", "Čeština"),
       ("de", "Deutsch", "Deutsch"),  # ← new
   ]
   _LOCALE_FILES: dict[str, str] = {
       "en": "docs/i18n/en.md",
       "cs": "docs/i18n/cs.md",
       "de": "docs/i18n/de.md",  # ← new
   }
   _README_TARGETS: dict[str, str] = {
       "en": "README.md",
       "cs": "docs/README.cs.md",
       "de": "docs/README.de.md",  # ← new
   }
   ```
   Then add a row to the `_BANNER_LABELS` dict in the same file, so
   the visible banner reads in your language rather than in English:
   ```python
   _BANNER_LABELS: dict[str, tuple[str, str, str]] = {
       # locale: (canonical label, other-languages label, self marker)
       "en": ("Canonical:", "Other languages:", "(this file)"),
       "cs": ("Hlavní jazyk:", "Ostatní jazyky:", "(tento soubor)"),
       "de": ("Hauptsprache:", "Weitere Sprachen:", "(diese Datei)"),  # ← new
   }
   ```
   A missing row is a hard error (exit 2) rather than a fallback to
   English — a Czech README with an English "Other languages:" heading
   is a bug, so the build refuses to produce one.

5. **Run the build:** `python scripts/i18n_build.py`. This
   regenerates `README.md` (canonical) and `docs/README.<lang>.md`
   from the corresponding source file. Verify the cross-link
   banner in the compiled README looks correct.

6. **Run the linter:** `python scripts/i18n_lint.py`. This counts
   `## X` headings per translation and warns if your file is
   much shorter or longer than the canonical — usually a sign of
   a missed section.

7. **Open a PR.** Title it like `i18n: add German (de) translation`.
   The build script re-generates the auto-managed cross-link banner,
   so the diff for your PR should include:
   - `docs/i18n/de.md` (your translation source)
   - `scripts/i18n_build.py` (3-line registration)
   - `README.md` (the canonical will get a new "Other languages"
     link to `docs/README.de.md`)
   - `docs/README.de.md` (the compiled file for your translation)

If anything in the build output looks wrong, see the "How the
build works" section or open an issue with the error output
attached.

### Translation style guide (lightweight)

- **Match GitHub tone.** Markdown with relative links, fenced
  code blocks, and tables. No HTML.
- **Don't reinvent structure.** If the canonical README has 15
  `## X` sections, your translation should too. The lint will
  warn you otherwise.
- **Technical terms stay in English** inside code spans:
  `- `~/.hermes/config.yaml`` is `- `~/.hermes/config.yaml``
  even in Czech (where one would normally use a backtick variant).
- **Don't translate UI strings here.** The tray's own labels are
  handled by `gettext`, not by the README sources — see
  [Adding a UI translation](#adding-a-ui-translation) below.
- **Date format / currency** — README rarely uses them; if you
  hit one, prefer ISO 8601 (`2026-07-22`).
- **Acronyms** — first usage parenthetical, e.g.
  "SNI (System Notification Item, KDE Plasma tray spec)".

## How the build works

`docs/i18n/<lang>.md` files are **the source of truth**. The build
script:

1. Reads each source file
2. Replaces the `<!-- i18n:available-languages:START --> … END -->`
   comment block with an auto-managed comment listing the available
   languages
3. Inserts a visible `> **Canonical:** Deutsch (this file)` /
   `> **Other languages:** …` banner right after the comment
4. Writes the result to `README.md` (for `en.md`) or
   `docs/README.<lang>.md` (for other locales)

That means:

- **Editing `README.md` directly** is futile — the build will
  overwrite your changes. Always edit `docs/i18n/en.md`.
- **Run `python scripts/i18n_build.py`** before committing, so
  the canonical / other-language READMEs stay in sync.
- **Run `python scripts/i18n_lint.py`** to catch forgotten
  sections in your translation.
- The build is **idempotent** — running it twice produces the
  same output.

## Adding a UI translation

The tray's own labels — menu entries, dialogs, tooltips — go through
stdlib `gettext`. There is no runtime dependency and no build step
beyond compiling the catalog.

1. **Copy the template as your starting point:**
   ```bash
   mkdir -p src/tray4hermes/_locales/de/LC_MESSAGES
   cp src/tray4hermes/_locales/tray4hermes.pot \
      src/tray4hermes/_locales/de/LC_MESSAGES/tray4hermes.po
   ```
   The template is regenerated from the source code by
   `./scripts/i18n_compile.sh`, so it always carries the English
   `msgid`s the runtime actually looks up, with empty `msgstr`s
   waiting for you.

2. **Translate the `msgstr` lines** and leave every `msgid` alone.
   Msgids are English by contract; `tests/test_i18n_runtime.py`
   scans the source with an AST walk and fails if a non-English
   literal shows up inside `_()`.

3. **Update the catalog header** — `Language: de\n`, plus your name
   in `Last-Translator` if you want the credit.

4. **Compile:** `./scripts/i18n_compile.sh`. This re-extracts the
   `.pot` template from the sources (needs `xgettext`; skipped with a
   warning if it is missing) and turns every `.po` under
   `src/tray4hermes/_locales/` into the `.mo` that ships inside the
   wheel. Commit both files — the `.mo` is package data, not a build
   artefact we regenerate at install time.

5. **Check it end to end:**
   ```bash
   python -m tray4hermes --language      # lists what the build ships
   python -m tray4hermes -L de           # runs the tray in your language
   ```
   Also open Settings and switch languages there: the tray re-labels
   itself live, so an untranslated string is visible immediately.

6. **Open a PR** titled like `i18n: add German (de) UI translation`.
   A UI translation and a README translation are separate PRs unless
   you are doing both for the same language.

## Adding a new feature (not just translation)

For non-translation PRs, follow the broader workflow:

1. **Open an issue first** describing the change (so we can discuss
   the design before you invest time).
2. **Include a small test** for anything user-visible.
3. **Run all gates** before pushing:
   ```bash
   ./scripts/dev.sh -v          # tests
   uv run ruff check src tests  # lint
   uv run ruff format src tests # format
   uv run bandit -c pyproject.toml -r src  # security scan
   ```
   CI re-runs the tests and the two ruff gates on Python 3.11, 3.12 and
   3.13 for every pull request, so a red pipeline is not a surprise —
   but finding it locally is faster. The security scan is not part of
   CI; run it yourself when you touch anything that spawns a process or
   reads a file path.

## Versioning and completed-work commits

tray4hermes follows **Semantic Versioning** and Conventional Commits. Every
completed user-visible work unit that is committed must include its version
bump in the same commit:

| Change | Commit type | Version bump |
|---|---|---|
| Backwards-compatible bug fix or polish | `fix:` / `perf:` | PATCH (third slot) |
| Backwards-compatible new capability | `feat:` | MINOR (second slot, patch resets to 0) |
| Breaking change (drop Python, switch to Qt6, …) | `feat!:` / `BREAKING CHANGE:` | MAJOR (first slot, lower slots reset) |
| Documentation, tests, or chore only | `docs:` / `test:` / `chore:` | none |

Every slot is **unbounded** — `2.0.99 + fix = 2.0.100`, not `2.1.0`.
The `feat:` slot is the most common place to land a release milestone;
use `fix:` for one-off polish. Reaching `3.0.0` should be a deliberate
act (e.g. switching to Plasma 6 / Qt6), not a surprise.

Before committing completed work:

1. Choose the Conventional Commit type from the table.
2. Bump the version with `python scripts/versioning.py
   patch|minor|major`.
3. Run the full quality gates.
4. Stage the implementation, tests, and version bump together in one commit.
5. Do not create a tag or GitHub release unless explicitly requested.

> ⚠️ Step 2 is **manual**. No hook infers the bump from your commit
> message, so nothing will stop a `fix:` that forgets to bump.
>
> CI does enforce one half of it: a pull request whose version is
> *lower* than the one on `main` fails. That is the failure that
> actually happened here — the version went 2.0.11 → 2.0.6 while no
> gate of any kind was running.

The package version has a single source of truth:
`src/tray4hermes/__init__.py::__version__`.

## Where to ask

- **Issue tracker:** https://github.com/MoDD0/tray4hermes/issues
  (GitHub is the canonical host — all issues, PRs and releases
  live there)
- **Security disclosures:** GitHub's "Report a vulnerability"
  button (Settings → Security) — please, **do not** post security
  issues publicly

## Out of scope (for this repo)

- Anything that would require reading `~/.hermes/auth.json` or the
  user's `.env` file. We never touch credentials.
- Custom tray backend designs (Wayland/Unity/etc.) are welcome but
  big projects — open an issue first to scope.
- New runtime dependencies. Single-dep projects stay simpler.
