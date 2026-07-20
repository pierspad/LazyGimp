"""One module per screen, as mixins composed by LazyGimpApp."""

from .landing import LandingPage
from .progress import InstallProgressPage
from .uninstall import UninstallPage
from .wizard import WizardPages

__all__ = ["LandingPage", "InstallProgressPage", "UninstallPage", "WizardPages"]
