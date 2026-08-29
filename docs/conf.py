"""Sphinx configuration for the backend documentation."""

project = "Ẹkúmidáyọ̀mí Backend"
author = "Ẹkúmidáyọ̀mí"
copyright = "2026, Ẹkúmidáyọ̀mí"
version = "0.1"
release = "0.1.0"

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build"]

language = "en"
nitpicky = True
myst_enable_extensions = ["colon_fence", "deflist"]

html_theme = "furo"
html_title = project
