# Strict Sphinx builds

## Causes and corrections

The previous clean build reported 503 diagnostics. Most were missing
autosummary stubs: automodapi generated plugin pages under a directory that
Sphinx excluded. The remaining warnings included duplicate instrument entries,
unparsed Google-style fields, native Qt signal help and unquoted SCPI commands.

- Replaced automodapi plugin listings with native Sphinx autosummary entries
  using canonical definition modules. Instrument listings now use the same
  approach, retaining the existing architectural explanation.
- Added a class template with members, undocumented members and inheritance.
  All 63 registered plugin entry points have generated detail pages. The
  generated `docs/_generated/api/` directory is ignored by Git and included by
  Sphinx. The previous automodapi cache remains excluded and untouched.
- Enabled Google-style Napoleon processing, retained NumPy-style support,
  recognised the project's Keyword Parameters section and rendered Attributes
  as variable fields to avoid duplicate property indexing.
- Added a documentation-only Qt extension. It recognises native PyQt signal
  help before Napoleon, then restores it as literal text afterwards. Authored
  signal documentation remains unchanged; no diagnostic category is disabled.
- Quoted `*CLS` and `*STB?` in the two owning instrument docstrings. Their
  executable ASTs remain identical to the committed source.
- The deployment action and contributor instructions now build with
  `-E -a -b html -W --keep-going`.

## Verification

- The complete strict HTML build passes with zero warnings and an empty
  warning log.
- A second strict build from a pristine documentation copy, excluding all
  generated pages, build output and doctrees, also passes with zero warnings.
  This verifies that API generation works without a local cache.
- All 63 registered plugins have generated API pages and indexed class targets.
  Across 330 authored/API HTML pages, 23,354 internal links, assets and anchors
  pass validation.
- Native signal help, authored RST preservation and temporary-state cleanup
  were checked independently. Instrument executable AST comparisons pass.
- Ruff check/format, whitespace checks and markdownlint pass on the changed
  configuration, documentation extension and note.

No instrument commands, plugin behaviour or application UI were changed.
The former automodapi extension remains installed in existing environments
but is no longer used by the Sphinx configuration.
