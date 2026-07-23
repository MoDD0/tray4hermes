# Tray4Hermes agent instructions

## Completed-work commits and versions

Use Semantic Versioning with Conventional Commits for every completed work unit:

- `fix:` or `perf:` → PATCH (`2.0.0` → `2.0.1`)
- `feat:` → MINOR (`2.0.1` → `2.1.0`)
- `type!:` or a `BREAKING CHANGE:` footer → MAJOR (`2.1.0` → `3.0.0`)
- `docs:`, `test:`, `chore:`, `refactor:` without a breaking change → no bump

The installed `prepare-commit-msg` hook derives the required bump and rejects
a missing or wrong version. Before committing, run:

```bash
python scripts/versioning.py patch|minor|major
```

Include the version change in the same commit as implementation and tests. Run the full test/lint/security gates before committing. Do not tag, publish, or push unless the user explicitly requests it.

The authoritative policy is in `CONTRIBUTING.md`; the version source of truth is `src/tray4hermes/__init__.py`.

## Documentation rule

Every user-visible behavior change must update the relevant documentation in
the same work unit and commit. Keep `docs/i18n/en.md` canonical, update
`docs/i18n/cs.md`, then run `python scripts/i18n_build.py` so generated README
files stay synchronized. Do not treat documentation as an optional follow-up.
