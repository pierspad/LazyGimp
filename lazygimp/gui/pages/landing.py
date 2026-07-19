"""Landing screen + Quick Setup (a prefilled plan handed to the
shared install-progress executor)."""

from __future__ import annotations

from ...compat import tk
from ...distro import detect_distro
from ...gimp_detect import find_gimp_binary, find_gimp_command
from ...gimp_install import appimage_present, gmic_available_on_this_release, gmic_installed, install_gimp_appimage, install_gimp_package_manager, install_gmic_only
from ...hardware import recommended_model_key, recommended_torch_index
from ...job import Job
from ...models import MODEL_BY_KEY, any_model_installed, model_path
from ...photogimp import install_photogimp, photogimp_installed
from ...plan import PlannedAction
from ...plugins import batcher_installed, install_batcher, install_segany_plugin, segany_plugin_installed, write_segany_plugin_settings
from ...sam_backend import backend_ready, bridge_self_test, install_sam_backend, write_sam_info
from ..dialogs import show_snackbar, themed_info
from ..helpers import autowrap_label
from ..icons import icon_canvas
from ..state import anything_installed
from ..theme import BG, CARD_BG, F_CARD_TITLE, F_HERO, F_SMALL, F_SUBTITLE, TEXT, TEXT_MUTED, F_ITEM_TITLE
from ..widgets import ModernCheckbox, RoundedButton, RoundedCard, bind_click_recursive
import os
import subprocess
import sys


class LandingPage:
    def show_landing(self):
        self.current_screen = "landing"
        for w in self.root_frame.winfo_children():
            w.destroy()

        wrap = tk.Frame(self.root_frame, bg=BG)
        wrap.pack(fill="both", expand=True)
        center = tk.Frame(wrap, bg=BG)
        center.place(relx=0.5, rely=0.4, anchor="center")

        tk.Label(center, text="LazyGimp", bg=BG, fg=TEXT, font=F_HERO).pack()
        tk.Label(center, text="GIMP + PhotoGIMP + G'MIC + SAM + Batcher, ready to use",
                 bg=BG, fg=TEXT_MUTED, font=F_SUBTITLE).pack(pady=(2, 10))
        distro = detect_distro()
        method_note = f"Recommended for this system: {'package manager (' + distro + ')' if distro else 'AppImage'}"
        tk.Label(center, text=method_note, bg=BG, fg=TEXT_MUTED, font=F_SMALL).pack(pady=(0, 24))

        row = tk.Frame(center, bg=BG)
        row.pack()
        CARD_W, CARD_H = 320, 255

        manage = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        manage.grid(row=0, column=0, padx=10)
        title_row = tk.Frame(manage.body, bg=CARD_BG)
        title_row.pack(anchor="w")
        icon_canvas(title_row, "gear", color=TEXT, size=22).pack(side="left", padx=(0, 8))
        tk.Label(title_row, text="Custom install", bg=CARD_BG, fg=TEXT, font=F_CARD_TITLE).pack(
            side="left")
        autowrap_label(
            manage.body,
            "Walk through PhotoGIMP, G'MIC, SAM and Batcher one page at a time, queue exactly what you "
            "want installed or removed, then run the whole checklist in one pass.",
            bg=CARD_BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(8, 16))
        open_btn = RoundedButton(manage.body, "Open (1)", variant="secondary", width=272, height=40,
                                  font=F_ITEM_TITLE, command=self.show_wizard)
        open_btn.pack(anchor="w", side="bottom")
        manage.finalize()
        bind_click_recursive(manage, self.show_wizard, skip=(open_btn,))

        auto = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        auto.grid(row=0, column=1, padx=10)
        title_row2 = tk.Frame(auto.body, bg=CARD_BG)
        title_row2.pack(anchor="w")
        icon_canvas(title_row2, "bolt", color=TEXT, size=22).pack(side="left", padx=(0, 8))
        tk.Label(title_row2, text="Quick setup", bg=CARD_BG, fg=TEXT, font=F_CARD_TITLE).pack(side="left")
        autowrap_label(
            auto.body,
            "Installs everything still missing, in order: PhotoGIMP, G'MIC, SAM (with a model picked "
            "for your hardware) and Batcher. Already-installed pieces are left alone.",
            bg=CARD_BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(8, 16))
        start_btn = RoundedButton(auto.body, "Start (2)", variant="primary", width=272, height=40,
                                   font=F_ITEM_TITLE, command=self.start_quick_setup)
        start_btn.pack(anchor="w", side="bottom")
        auto.finalize()
        bind_click_recursive(auto, self.start_quick_setup, skip=(start_btn,))

        if anything_installed():
            btn_row = tk.Frame(center, bg=BG)
            btn_row.pack(pady=(24, 0))
            if find_gimp_command():
                RoundedButton(btn_row, "Close installer and open GIMP", variant="primary", icon="bolt",
                              width=400, height=46, command=self.launch_gimp_and_close).pack(pady=(0, 14))
            RoundedButton(btn_row, "Uninstall from this system", variant="danger", icon="trash",
                          width=400, height=46, command=self.show_uninstall_confirm).pack()

        # The installer is disposable by design: this drives the same
        # --ephemeral self-destruction (binary, .pyz or source folder) via
        # the env flag util._self_destruct_if_ephemeral() checks on exit.
        # Text is part of the checkbox: the whole row is clickable and
        # hovers as one.
        self._ephemeral_var = tk.BooleanVar(
            value="--ephemeral" in sys.argv or os.environ.get("LAZYGIMP_INSTALLER_EPHEMERAL") == "1")

        def sync_ephemeral():
            os.environ["LAZYGIMP_INSTALLER_EPHEMERAL"] = "1" if self._ephemeral_var.get() else "0"

        ModernCheckbox(center, self._ephemeral_var, command=sync_ephemeral,
                       text="Delete this installer when it closes — leaves the folder clean",
                       font=F_SUBTITLE,
                       ).pack(pady=(26, 0))
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
        self.root.destroy()

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
                lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0])))

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
