#!/usr/bin/env python3
"""Thin launcher for a source checkout — the real code lives in lazygimp/.

Kept so the historic `python3 lazygimp.py` invocation keeps working unchanged.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lazygimp.cli import main

if __name__ == "__main__":
    main()
