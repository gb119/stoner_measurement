Plugin Tab Ordering
===================

This page defines the expected configuration-tab ordering for plugin developers.

Principles
----------

Users should be able to find the most commonly used settings first, while
maintaining a consistent structure across plugin types.

Recommended order
-----------------

1. Instance tab (the tab named after the plugin instance) should be first.
2. If scan, sweep, or other primary experiment-definition settings are not on
   the instance tab, they should appear immediately after it.
3. Additional configuration tabs should follow in order of typical usage.
4. More advanced or specialised configuration tabs should appear later.
5. The About/help tab should be last.

Rationale
---------

- The first tab is treated as the primary configuration surface for the plugin.
- The instance name should always be easy to find.
- Frequently used experimental settings should appear before advanced options.
- Help and reference material should not displace operational settings.

Guidance for developers
-----------------------

When extending ``config_tabs()``:

- Preserve the instance tab as the first tab whenever practical.
- Insert additional workflow-specific tabs after the primary tab.
- Place advanced settings after core configuration tabs.
- Keep the About tab at the end of the tab list.

This convention is intended as guidance for maintaining a consistent user
experience across monitor, trace, scan, sweep, transform, and command plugins.