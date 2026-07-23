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

## Ground rules (pružné, ale platné)

1. **Don't break the tests.** 56 tests must stay green.
2. **Don't add new runtime dependencies** without discussion — the
   package has one runtime dep (`PyQt5`), and we want to keep it
   that way.
3. **No secrets in the diff.**
   `grep -rE "sk-[a-z0-9]{16,}|api_key.*[a-z0-9]{20,}"` should be empty.
4. **No writes to `~/.hermes/*`** from inside the tray — that area
   is owned by Hermes Agent.
5. **MIT-compatible contributions.** Same license as the project.

## Adding a new translation (language)

We support **English (canonical)** and **Czech** out of the box.
For other languages, follow these conventions so the build tools
stay sane and the language picker stays in sync.

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
   In `rewrite_header_banner()`, add a label for your locale in
   the `canonical_label` dict so "Canonical: Deutsch (this file)"
   reads naturally.

5. **Run the build:** `python scripts/i18n_build.py`. This
   regenerates `README.md` (canonical) and `docs/README.<lang>.md`
   from the corresponding source file. Verify the cross-link
   banner in the compiled README looks correct.

6. **Run the linter:** `python scripts/i18n_lint.py`. This counts
   `## X` headings per translation and warns if your file is
   much shorter or longer than the canonical — usually a sign of
   a missed section.

7. **Open a PR.** Title it like `i18n: add German (de) translation`.
   The build script will re-generate the auto-mananged cross-link
   banner, so the diff for your PR should include:
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
- **UI strings in code are Czech-friendly.** Tray toolbars are in
  Czech and that's intentional. Don't translate `Kopírovat`,
  `Vyčistit` to `Copy`, `Clear` — leave them. (If we ever
  internationalise the UI strings, that's a separate project
  using `gettext`.)
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

## Versioning and completed-work commits

tray4hermes follows **Semantic Versioning** and Conventional Commits. Every
completed user-visible work unit that is committed must include its version
bump in the same commit:

| Change | Commit type | Version bump | Example from `2.0.0` |
|---|---|---|---|
| Backwards-compatible bug fix or promised correction | `fix:` / `perf:` | PATCH | `2.0.1` |
| Backwards-compatible new capability | `feat:` | MINOR | `2.1.0` |
| Breaking API/config/behavior change | `type!:` or `BREAKING CHANGE:` | MAJOR | `3.0.0` |
| Docs/tests/chore only | `docs:` / `test:` / `chore:` | none | unchanged |

Before committing completed work:

1. Choose the Conventional Commit type from the table.
2. Install hooks once with `pre-commit install --hook-type pre-commit
   --hook-type prepare-commit-msg`. The `prepare-commit-msg` hook derives the
   required bump from the commit type and rejects a missing or wrong bump.
3. If hooks are unavailable, run `python scripts/versioning.py
   patch|minor|major` manually when required.
4. Run the full quality gates.
5. Stage the implementation, tests, and version bump together in one commit.
6. Do not create a tag or GitHub release unless explicitly requested.

The package version has a single source of truth:
`src/tray4hermes/__init__.py::__version__`.

## Where to ask

- **Issue tracker:** https://github.com/MoDD0/tray4hermes/issues
  (GitHub is the canonical host; the Forgejo mirror does not
  accept issues)
- **Security disclosures:** GitHub's "Report a vulnerability"
  button (Settings → Security) — please, **do not** post security
  issues publicly

## Out of scope (for this repo)

- Anything that would require reading `~/.hermes/auth.json` or the
  user's `.env` file. We never touch credentials.
- Custom tray backend designs (Wayland/Unity/etc.) are welcome but
  big projects — open an issue first to scope.
- New runtime dependencies. Single-dep projects stay simpler.
