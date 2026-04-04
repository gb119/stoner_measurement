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

# -- Project information -------------------------------------------------------

project = "Stoner Measurement"
copyright = "2024, Gavin Burnell"
author = "Gavin Burnell"
release = "0.1.0"

# -- General configuration ----------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

autosummary_generate = True
napoleon_google_docstring = False
napoleon_numpy_docstring = True

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

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
