# Measurement reference structure and screenshots

## Navigation

- `docs/rig_controls.rst` is now the general Controllers page. Its child
  references cover temperature, magnet, motor, pressure/flow and X-ray.
- `docs/keithley_meters.rst` introduces the four trace modes, point scans and
  set commands, with child guides and a shared connections/triggering page.
- Existing temperature, X-ray, Pulse Delta and point-command page URLs remain
  valid. The point-command page now includes the 2400 point scan explicitly.
- Catalogue labels match `src/stoner_measurement/conf/plugin_catalogue.yaml`.
  Source review covered current settings, output columns, differential modes,
  session ownership and the status-bar connection actions.

## Screenshots

Added 20 PNG screenshots under `docs/_static/screenshots/`, all captured from
real Qt widgets using the application's dark theme, Segoe UI and Windows
fonts. Controller examples use only built-in simulators. Keithley examples
construct configuration pages without connecting, configuring or measuring
physical instruments. Every screenshot has alternative text and a caption.

The temporary capture helper and isolated YAML/QSettings state are under
`.pytest-runtime/`. Captures retain hidden scan previews and drain Qt deferred
deletes before rendering to avoid stale overlapping controls. All simulator
engines are shut down afterwards. The configuration forms use illustrative
addresses rather than a connected rig's identity.

## Validation

- Static documentation-skill checks passed for all eight Keithley entry
  points. Their executable ASTs match `HEAD`; no plugin docstrings, About
  overrides or runtime code were changed.
- Browser review confirmed the Controllers hierarchy, Keithley comparison
  table, guide navigation and embedded screenshots.
- Clean Sphinx builds of the committed and revised documentation both report
  503 existing API/autosummary/docstring diagnostics. The normal HTML build
  succeeds; strict `-W` remains blocked by that existing baseline. Comparison
  of normalised warning inventories found no additional diagnostics.
- All 1,469 internal links/assets/anchors across the 29 authored pages passed;
  all 20 screenshot assets have alternative text and both hub hierarchies are
  complete. The final incremental strict Sphinx build passed without warnings.
- The 16 selected existing docstring/About/configuration checks passed on
  Python 3.14/PyQt5. No tests were added or changed.
- Markdownlint checks this note before commit. Instrument behaviour and
  physical trigger timing were not bench-tested by this documentation work.
