# Temperature-panel settings readbacks

Remote timing capture showed an 88-second continuous GUI-thread burst after
ITC503 connection, including six complete 32-row, four-column auto-PID table
reads (768 q commands). Connecting the secondary 340 triggered four further
primary table reads alongside its own configuration queries. VISA manager,
resource open and Device Clear completed in milliseconds.

Connection notifications previously rebuilt both controllers' loop widgets,
read every loop, loaded zones through multiple paths, and fetched input settings
and curve metadata. The panel now tracks connected driver identities and keeps
unchanged loop groups and input editors. Only newly connected/replaced loop
groups get their initial settings read. Duplicate notifications and showing the
panel preserve existing controls. Primary and secondary connection changes
invalidate only their own input settings.

Zones load on first opening the Zone Table page and on a loop change while it
is visible. The current loaded table survives notification and tab changes;
Read remains the explicit refresh. Input Settings now has FontAwareTabWidget
Primary/Secondary sub-tabs. Each controller's input settings and curve names
load on first selecting its own page, with Read All available for refresh.
Failed loads remain retryable; controls and Apply/Write stay disabled until
successful readback. Read buttons remain usable. No nested Qt event loops or
processEvents calls were introduced; repaint requests show disabled state
without permitting concurrent user actions during hardware reads.

The first-access reads remain synchronous; moving all session operations to
workers is separate work. Opening an ITC503 zone table can still be slow,
but it is no longer incidental connection work or automatically repeated.
This initial limitation is addressed by the subsequent
[background-operation implementation](2026-11-12-temperature-background-operations.md).

The remote magnet was a Mercury iPS. The user confirmed its initial write
timeout occurred while remote access was disabled at the front panel; it
succeeded after enabling remote access. This is not evidence of a driver fault.

Verification: 243 focused panel, controller and driver tests passed, including
hardware-command Apply regressions, native 340 input editors and shared
stability. Full collection succeeded (4,534 tests). Hardware timing and other
Qt bindings remain untested locally.
