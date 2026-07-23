"""Landing screen + Quick Setup (a prefilled plan handed to the
shared install-progress executor) — PySide6 port of ``gui/pages/landing.py``.

Behavior is preserved exactly; only the toolkit changed. See
``lazygimp/gui/README.md`` for the old (Tk) -> new (Qt) API table this
was built against.
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...distro import detect_distro
from ...gimp_detect import find_gimp_binary, find_gimp_command
from ...gimp_install import (
    appimage_present, gmic_available_on_this_release, gmic_installed, install_gimp_appimage,
    install_gimp_package_manager, install_gmic_only,
)
from ...hardware import recommended_model_key, recommended_torch_index
from ...job import Job
from ...models import MODEL_BY_KEY, any_model_installed, model_path
from ...photogimp import install_photogimp, photogimp_installed
from ...plan import PlannedAction
from ...plugins import (
    batcher_installed, install_batcher, install_segany_plugin, segany_plugin_installed,
    write_segany_plugin_settings,
)
from ...sam_backend import backend_ready, bridge_self_test, install_sam_backend, write_sam_info
# state.py is pure detection logic (no Tk import) — reused as-is rather
# than duplicated/re-ported, see gui/state.py.
from ...gui.state import anything_installed
from ..dialogs import show_snackbar, themed_info
from ..icons import icon_label
from ..theme import F_CARD_TITLE, F_HERO, F_ITEM_TITLE, F_SMALL, F_SUBTITLE, TEXT, TEXT_MUTED, qfont
from ..widgets import BoolVar, ModernCheckbox, RoundedButton, RoundedCard, autowrap_label, bind_click_recursive


def _ensure_vbox(widget: QWidget) -> QVBoxLayout:
    layout = widget.layout()
    if layout is None:
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
    return layout


def _clear_root_frame(root_frame: QWidget, keep=None) -> QVBoxLayout:
    """Removes every existing screen widget from root_frame, mirroring the
    Tk engine's ``for w in root_frame.winfo_children(): w.destroy()`` sweep
    at the top of every show_*() method. ``keep``, if given, is left alone
    (not removed/deleted) — used by the wizard's landing<->wizard
    transition, which needs both screens to coexist briefly; see
    ``gui/pages/wizard.py``'s ``_show_landing_over()`` for the Tk original.
    The actual slide animation is the wizard page's responsibility to
    build on top of this hook (out of scope here) — this just guarantees
    the ``_preserve``/``self._landing_frame`` contract still exists so
    that code has something to grab onto.
    """
    layout = _ensure_vbox(root_frame)
    for i in reversed(range(layout.count())):
        item = layout.itemAt(i)
        w = item.widget()
        if w is None or w is keep:
            continue
        layout.removeWidget(w)
        w.setParent(None)
        w.deleteLater()
    return layout


def _plain_label(parent, text, font, fg=TEXT):
    lbl = QLabel(text, parent)
    lbl.setFont(qfont(font))
    lbl.setStyleSheet(f"color: {fg}; background: transparent;")
    lbl.setAlignment(Qt.AlignHCenter)
    return lbl


class LandingPage:
    def show_landing(self, _preserve=None):
        self.current_screen = "landing"
        root_layout = _clear_root_frame(self.root_frame, keep=_preserve)

        wrap = QWidget(self.root_frame)
        self._landing_frame = wrap
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(wrap)

        # Tk placed `center` at relx=0.5, rely=0.4 (anchor="center") inside
        # a `wrap` that filled the whole root_frame. Qt has no direct
        # equivalent inside a real QLayout, so a 2:3 stretch split above/
        # below approximates the same "just above center" vertical
        # position while keeping this a real (resizable) layout.
        wrap_layout.addStretch(2)
        center = QWidget(wrap)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        wrap_layout.addWidget(center, 0, Qt.AlignHCenter)
        wrap_layout.addStretch(3)

        title = _plain_label(center, "LazyGimp", F_HERO, TEXT)
        center_layout.addWidget(title, 0, Qt.AlignHCenter)

        subtitle = _plain_label(
            center, "GIMP + PhotoGIMP + G'MIC + SAM + Batcher, ready to use", F_SUBTITLE, TEXT_MUTED)
        center_layout.addSpacing(2)
        center_layout.addWidget(subtitle, 0, Qt.AlignHCenter)
        center_layout.addSpacing(10)

        distro = detect_distro()
        method_note = f"Recommended for this system: {'package manager (' + distro + ')' if distro else 'AppImage'}"
        note = _plain_label(center, method_note, F_SMALL, TEXT_MUTED)
        center_layout.addWidget(note, 0, Qt.AlignHCenter)
        center_layout.addSpacing(24)

        row = QWidget(center)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(20)
        center_layout.addWidget(row, 0, Qt.AlignHCenter)

        CARD_W, CARD_H = 320, 255

        manage = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        row_layout.addWidget(manage)
        manage_body = QVBoxLayout(manage.body)
        manage_body.setContentsMargins(0, 0, 0, 0)
        manage_body.setSpacing(0)

        title_row = QWidget(manage.body)
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)
        title_row_layout.setSpacing(8)
        title_row_layout.addWidget(icon_label(title_row, "gear", color=TEXT, size=22))
        title_row_layout.addWidget(_plain_label(title_row, "Custom install", F_CARD_TITLE, TEXT))
        title_row_layout.addStretch(1)
        manage_body.addWidget(title_row)

        manage_desc = autowrap_label(
            manage.body,
            "Walk through PhotoGIMP, G'MIC, SAM and Batcher one page at a time, queue exactly what you "
            "want installed or removed, then run the whole checklist in one pass.",
            font=F_SMALL,
        )
        manage_body.addSpacing(8)
        manage_body.addWidget(manage_desc)
        manage_body.addStretch(1)

        open_btn = RoundedButton(manage.body, "Open (1)", variant="secondary", width=272, height=40,
                                  font=F_ITEM_TITLE, command=self.show_wizard)
        manage_body.addWidget(open_btn, 0, Qt.AlignLeft)
        manage.finalize()
        bind_click_recursive(manage, self.show_wizard, skip=(open_btn,))

        auto = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        row_layout.addWidget(auto)
        auto_body = QVBoxLayout(auto.body)
        auto_body.setContentsMargins(0, 0, 0, 0)
        auto_body.setSpacing(0)

        title_row2 = QWidget(auto.body)
        title_row2_layout = QHBoxLayout(title_row2)
        title_row2_layout.setContentsMargins(0, 0, 0, 0)
        title_row2_layout.setSpacing(8)
        title_row2_layout.addWidget(icon_label(title_row2, "bolt", color=TEXT, size=22))
        title_row2_layout.addWidget(_plain_label(title_row2, "Quick setup", F_CARD_TITLE, TEXT))
        title_row2_layout.addStretch(1)
        auto_body.addWidget(title_row2)

        auto_desc = autowrap_label(
            auto.body,
            "Installs everything still missing, in order: PhotoGIMP, G'MIC, SAM (with a model picked "
            "for your hardware) and Batcher. Already-installed pieces are left alone.",
            font=F_SMALL,
        )
        auto_body.addSpacing(8)
        auto_body.addWidget(auto_desc)
        auto_body.addStretch(1)

        start_btn = RoundedButton(auto.body, "Start (2)", variant="primary", width=272, height=40,
                                   font=F_ITEM_TITLE, command=self.start_quick_setup)
        auto_body.addWidget(start_btn, 0, Qt.AlignLeft)
        auto.finalize()
        bind_click_recursive(auto, self.start_quick_setup, skip=(start_btn,))

        if anything_installed():
            center_layout.addSpacing(24)
            btn_row = QWidget(center)
            btn_row_layout = QVBoxLayout(btn_row)
            btn_row_layout.setContentsMargins(0, 0, 0, 0)
            btn_row_layout.setSpacing(14)
            center_layout.addWidget(btn_row, 0, Qt.AlignHCenter)

            if find_gimp_command():
                open_gimp_btn = RoundedButton(btn_row, "Close installer and open GIMP", variant="primary",
                                               icon="bolt", width=400, height=46,
                                               command=self.launch_gimp_and_close)
                btn_row_layout.addWidget(open_gimp_btn)

            uninstall_btn = RoundedButton(btn_row, "Uninstall from this system", variant="danger", icon="trash",
                                           width=400, height=46, command=self.show_uninstall_confirm)
            btn_row_layout.addWidget(uninstall_btn)

        # The installer is disposable by design: this drives the same
        # --ephemeral self-destruction (binary, .pyz or source folder) via
        # the env flag util._self_destruct_if_ephemeral() checks on exit.
        # Text is part of the checkbox: the whole row is clickable and
        # hovers as one (native QCheckBox behavior).
        self._ephemeral_var = BoolVar(
            "--ephemeral" in sys.argv or os.environ.get("LAZYGIMP_INSTALLER_EPHEMERAL") == "1")

        def sync_ephemeral():
            os.environ["LAZYGIMP_INSTALLER_EPHEMERAL"] = "1" if self._ephemeral_var.get() else "0"

        ephemeral_cb = ModernCheckbox(
            center, self._ephemeral_var, command=sync_ephemeral,
            text="Delete this installer when it closes — leaves the folder clean",
            font=F_SUBTITLE,
        )
        center_layout.addSpacing(26)
        center_layout.addWidget(ephemeral_cb, 0, Qt.AlignHCenter)
        sync_ephemeral()

    def launch_gimp_and_close(self):
        cmd = find_gimp_command()
        if not cmd:
            show_snackbar(self, "GIMP not found", tone="error")
            return
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception as e:
            show_snackbar(self, f"Couldn't launch GIMP: {e}", tone="error")
            return
        # Qt counterpart of Tk's self.root.destroy() — closes the top-level
        # window (and, with the default quitOnLastWindowClosed, ends the
        # QApplication event loop).
        self.root.close()

    # ---- quick setup: everything missing, in priority order -----------

    def start_quick_setup(self):
        if self.busy:
            themed_info(self.root, "Busy", "Setup is already running.")
            return
        # One-click setup is just a prefilled plan handed straight to the
        # same executor the wizard's Review page uses — no separate code
        # path, no separate "what to install" logic to keep in sync.
        self.show_install_progress(self._build_quick_setup_plan())

    def _build_quick_setup_plan(self) -> list["PlannedAction"]:
        actions: list[PlannedAction] = []

        if not find_gimp_binary() and not appimage_present():
            if detect_distro():
                actions.append(PlannedAction(
                    "gimp:install", "Install GIMP (package manager)", "install",
                    lambda job: install_gimp_package_manager(job, include_gmic=False)))
            else:
                actions.append(PlannedAction(
                    "gimp:install", "Install GIMP (AppImage)", "install",
                    lambda job: install_gimp_appimage(job)))

        if not photogimp_installed():
            actions.append(PlannedAction(
                "photogimp:install", "Install PhotoGIMP", "install",
                lambda job: install_photogimp(job, gimp_command=find_gimp_command())))

        if gmic_available_on_this_release() and not gmic_installed():
            actions.append(PlannedAction("gmic:install", "Install G'MIC", "install",
                                          lambda job: install_gmic_only(job)))

        if not segany_plugin_installed():
            actions.append(PlannedAction("sam_plugin:install", "Install the SAM plug-in", "install",
                                          lambda job: install_segany_plugin(job)))

        if not backend_ready():
            actions.append(PlannedAction(
                "sam_backend:install", "Set up the SAM Python backend", "install",
                lambda job: install_sam_backend(job, recommended_torch_index(self.hw))))

        if not any_model_installed():
            rec = MODEL_BY_KEY[recommended_model_key(self.hw)]

            def install_recommended(job: Job, rec=rec):
                if job.download(rec.url, model_path(rec), job.cancel_event):
                    write_segany_plugin_settings(rec)
                    write_sam_info([rec.key])
                    bridge_self_test(job, rec)

            actions.append(PlannedAction(f"sam_model:{rec.key}:install",
                                          f"Download the recommended SAM model: {rec.label}",
                                          "install", install_recommended))

        if not batcher_installed():
            actions.append(PlannedAction("batcher:install", "Install Batcher", "install",
                                          lambda job: install_batcher(job)))

        return actions
