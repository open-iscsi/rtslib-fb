"""
rtslib_fb.py - Backwards compatibility module for rtslib

This module provides backwards compatibility for code that imports 'rtslib_fb'.
It re-exports all public names from the 'rtslib' module.

Usage:
    from rtslib_fb import RTSRoot, Target, TPG  # etc.

Note: This compatibility layer may be deprecated in future versions.
Please consider updating your imports to use 'rtslib' directly.
"""

import rtslib
from rtslib import *  # noqa: F403

# Explicitly import and re-export submodules
from rtslib import alua, fabric, node, root, target, tcm, utils  # noqa: F401

# Re-export all public names from rtslib
__all__ = rtslib.__all__
