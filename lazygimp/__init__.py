"""LazyGimp — GIMP + PhotoGIMP + G'MIC + SAM (Segment Anything) + Batcher.

One installer, GUI (Tkinter) and CLI, split into small modules:

    constants     where things live on disk + upstream pins
    models        SAM model registry
    hardware      GPU/CPU detection (picks a sane default model)
    distro        distro / package-manager abstraction
    gimp_detect   what GIMP is installed, where its config lives
    job           background work + logging
    plan          the wizard's data model (planned actions)
    gimp_install  GIMP via package manager or Flatpak
    photogimp     the PhotoGIMP configuration layer
    plugins       plug-in folders (Batcher, seganyplugin)
    sam_backend   SAM venv + PyTorch backend
    sam3          SAM 3 (gated on Hugging Face)
    gui           the Tkinter app (optional — needs python3-tk)
    cli           argparse commands + main()

Run `python3 installer.py` (checkout), `python3 installer.pyz` (zipapp) or
the prebuilt binary. No arguments opens the GUI; see `--help` for the CLI.
"""
__version__ = "0.0.0.dev0"
