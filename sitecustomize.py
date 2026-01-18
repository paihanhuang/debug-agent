"""
Project-local Python site customization.

This repo is often used in environments that have globally-installed pytest
plugins (e.g., ROS) which can crash pytest collection if their dependencies are
missing. Disabling plugin auto-load keeps tests self-contained and reproducible.
"""

import os

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

