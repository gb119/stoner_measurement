# Shared Oxford protocol refactor

Verified IPS120 acknowledgement rules against the manufacturer-authored
*IPS120-10 Operator's Handbook*, Issue 06, November 2000, sections 5.2–5.3
(printed pp. 22–23) and 6.1 (p. 30):
[Oxford handbook](https://groups.spa.umn.edu/zudovlab/manuals/cryogenics/IPS12010.pdf).
Actions return the command letter alone; rejected commands return a leading `?`.
All `Q` communications-mode commands, including Q4/Q6, have no acknowledgement.
Commands prefixed with `$` explicitly suppress replies. Front-panel button presses
can delay responses until release.

`OxfordProtocol` now owns reply expectations, acknowledgement validation, echo
removal and numeric payload parsing for both IPS120 and ITC503. `BaseInstrument`
holds the instrument lock through each write/read/validation transaction, including
when optional error polling is disabled. IPS120 setters now consume their replies.
Acknowledgements are validated before query-style echo removal, so doubled echoes
cannot masquerade as valid single-letter replies. Numeric parsing accepts matching
echoes in either case, but rejects unrelated alphabetic prefixes.

Malformed or missing acknowledgements propagate errors without retrying the action.
An IPS120 remote-mode acknowledgement failure closes the newly opened transport.
No new delays, resynchronisation or control-mode changes are included. Physical
hardware validation of the acknowledgement transactions remains outstanding.

Validation: 1,053 tests passed on Python 3.14.7 and offscreen PyQt5, covering
`tests/unit/instruments`, `tests/unit/control/test_magnet_constant_configuration.py`
and `tests/test_magnet_control.py`. Ruff passed for all changed Python files.
Pytest used `--basetemp=.pytest-oxford-tmp` because the default temporary directory
was inaccessible. New transaction contracts are in
`tests/unit/instruments/contracts/test_oxford_transactions.py`; existing driver and
connection tests retain coverage with explicit acknowledgement replies.
