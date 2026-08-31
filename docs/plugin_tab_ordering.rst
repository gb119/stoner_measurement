Plugin Tab Ordering
===================

This page defines the expected configuration-tab ordering for plugin developers.

Principles
----------

Users should be able to find the most commonly used settings first, while
maintaining a consistent structure across plugin types.

Recommended order
-----------------

1. The primary role-based tab, such as General, Data, Scan, or Sweep, should be
   first and should include the instance-name controls where appropriate.
2. Additional primary experiment-definition settings should appear
   immediately after it.
3. Additional configuration tabs should follow in order of typical usage.
4. More advanced or specialised configuration tabs should appear later.
5. The About/help tab should be last.

Rationale
---------

- The first tab is treated as the primary configuration surface for the plugin.
- The instance name should always be easy to find without being repeated in
  every tab title.
- Frequently used experimental settings should appear before advanced options.
- Help and reference material should not displace operational settings.

Guidance for developers
-----------------------

When extending ``config_tabs()``:

- Preserve the primary role-based tab as the first tab whenever practical.
- Keep tab titles concise; do not prefix them with the plugin or class name.
- Insert additional workflow-specific tabs after the primary tab.
- Place advanced settings after core configuration tabs.
- Keep the About tab at the end of the tab list.

This convention is intended as guidance for maintaining a consistent user
experience across monitor, trace, scan, sweep, transform, and command plugins.
