# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

try:
    from better import better_theme_path

    _better_theme_available = True
except ImportError:
    _better_theme_available = False

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "_ext"))

# -- Project information -------------------------------------------------------

project = "Stoner Measurement"
copyright = "2024, Gavin Burnell"  # pylint: disable=redefined-builtin
author = "Gavin Burnell"
release = "0.1.0"

# -- General configuration ----------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "qt_signals",
]

autosummary_generate = True
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_custom_sections = [("Keyword Parameters", "params_style")]
# Keep class attribute descriptions without indexing them a second time beside
# the properties/methods documented by autoclass :members:.
napoleon_use_ivar = True
autodoc_mock_imports = [
    "PyQt6",
    "pyvisa",
    "pyqtgraph",
]

templates_path = ["_templates"]
# The former automodapi cache may remain in an existing checkout. New native
# autosummary pages live in _generated/api and must be included in the build.
exclude_patterns = ["_build", "_generated/automodapi", "Thumbs.db", ".DS_Store"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "PyQt6": ("https://www.riverbankcomputing.com/static/Docs/PyQt6/", None),
}

# -- Options for HTML output --------------------------------------------------

if _better_theme_available:
    html_theme = "better"
    html_theme_path = [better_theme_path]
else:
    html_theme = "alabaster"

html_logo = "_static/StonerLogo2.png"
html_static_path = ["_static"]
