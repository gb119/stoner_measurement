# Copilot general instructions

## Critical rules

- Prefer widgets from ``ui.widgets`` over stock Qt widgets.
- Route all hardware interaction through instrument drivers in the
  ``instruments`` sub-package.
- Generate instrument-specific commands only in driver code, not in UI code or
  sequence plugins.
- Use Google-style docstrings in British English.
- Class docstrings on concrete classes in the plugins hierarchy are used as end user
  documentation.
- For public APIs, document arguments, keyword parameters, return values,
  raised exceptions, attributes, notes, and examples as applicable.
- Follow naming, import ordering, line-length, whitespace, and Markdown rules
  in this file.

## Project Context

This application performs scientific measurements by communicating with lab
instruments over USB, Serial, GPIB, and Ethernet. It provides:

- UI for measurement-specific configuration, such as instrument selection,
  communication addresses, and instrument-specific settings
- UI for defining a measurement sequence
- rendering of the measurement sequence into Python code for execution in a
  sequence engine
- asynchronous communication of data and status from the sequence engine back
  to the UI

## UI guidelines

- Prefer widgets from ``ui.widgets`` over stock Qt widgets.
- For quantities with physical units, display units in the widget.
- Where values fall outside the range 0.1-1000, support SI prefixes.
- Use British English spelling.

## Hardware Interaction

- All hardware interaction must go through instrument drivers in the
  ``instruments`` sub-package.
- The driver package defines a class hierarchy for instrument types
  (e.g. power supplies, controllers, meters) and concrete instrument
  subclasses.
- Generate all instrument-specific commands in driver code, not in sequence
  plugins or UI code.
- Keeping command generation in drivers makes malformed commands easier to
  trace.

## Docstring formatting

Apply these rules to all Python docstrings for functions, classes, methods, and
modules:

- Use Google-style docstrings.
- Use British English.
- Start with a one-line summary on the opening line and end it with a period.

For end-user documentation docstrings on concrete classes in the plugins hierarchy, do the
following:
- Start with a description of the purpose of the plugin aimed at the end user doing
  measurements.
- Describe the configuration tabs and options for the end-user audience.
- Describe the instance attributes (including inherited ones) for the more advanced user
  interacting via the Script tab or QtConsole.
- Give examples of interacting with the plugin via the console.

For public classes, methods, and functions, do the following:
- Use ``Args:`` for positional arguments.
- Use ``Keyword Parameters:`` for keyword arguments.
- Format parameters as ``name (type):`` followed by an indented description.
- Use ``Returns:`` for return values.
  - For a single return value, use ``(type):`` followed by an indented
    description.
  - For tuples, document each returned value as a separate value block.
- Use ``Raises:`` for explicitly raised exceptions.
- Use ``Attributes:`` for class attributes, using the same structure as
  parameters.
- Use ``Notes:`` for algorithm details or similar supporting information.
- Use ``Examples:`` for usage examples.
- Document constructor behaviour in the class docstring rather than in the
  ``__init__`` docstring.

For private methods and functions:
- If used outside the immediate scope (e.g. by subclasses or other modules),
  document them like public APIs.
- Otherwise, only the summary is required; other sections are optional.

For module docstrings:
- Include a brief overview of the module contents and their common themes.

## Code formatting

### Naming

The following apply to entities created by Copilot. Unless specifically
instructed, do not rename existing entities that do not conform to the
following.

- Classes: PascalCase
- Functions, methods, and non-module-level variables: snake_case
- Module-level variables: CAPITAL_CASE

### Imports

Group imports in this order:

- standard library imports
- well-known third-party packages such as numpy, matplotlib, scipy, pandas
- other third party packages
- imports from within this package, including relative imports

Within each group, do the following:
- sort imports alphabetically.
- combine imports from the same module where practical

### Line length

- Use a maximum line length of 79 characters in user examples.
- Use a maximum line length of 119 characters elsewhere.
- Otherwise, follow Black formatting conventions.
- Avoid line splits incompatible with the Python versions specified in the
  package build scripts.
- Remove trailing whitespace at the end of lines.
- Ensure blank lines only contain an end of line character and not any other
  whitespace.

## Issues and bugs discovered during Copilot and other LLM operations

If a new issue or bug is discovered during editing or creating other features,
create a GitHub issue to track it. When creating issues, include:

- A clear, descriptive title
- The file path and line number where the issue occurs
- A detailed description of the issue
- Steps to reproduce (if applicable)
- Suggested fixes or approaches (if known)
- Appropriate labels (bug, enhancement, documentation, etc.)

If a GitHub issue is fixed during your work, close the issue with a reference to
the commit or PR that fixed it.

## Markdown formatting

When changing Markdown files, follow these guidelines:

- Use markdownlint to identify errors in Markdown formatting and fix any it
  flags.
- Use a maximum line length of 119 characters.
- Use British English spellings in text except where code requires differently.
- Pay particular attention to spacing around lists, headers and code blocks.
- Verify that files referenced in Markdown files, such as images, actually exist.
