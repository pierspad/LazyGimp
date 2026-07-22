"""One module per screen, as mixins composed by LazyGimpApp — PySide6
counterpart of ``lazygimp/gui/pages/__init__.py``."""

from .landing import LandingPage
from .progress import InstallProgressPage
from .uninstall import UninstallPage
from .wizard import WizardPages

__all__ = ["LandingPage", "InstallProgressPage", "UninstallPage", "WizardPages"]
