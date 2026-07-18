"""The paginated setup wizard (GIMP > PhotoGIMP > G'MIC > SAM >
Batcher > Review). Every page only queues PlannedActions into
self.plan; nothing here touches disk."""

from __future__ import annotations

from ...compat import tk, ttk
from ...constants import APPIMAGE_DIR, GMIC_DOWNLOAD_PAGE, SAM3_HF_PAGE, SAM3_HF_REPO_ID, TORCH_INDEX_URLS, VENV_DIR
from ...distro import detect_distro
from ...gimp_detect import find_gimp_command
from ...gimp_install import appimage_present, gimp_native_installed, gmic_available_on_this_release, gmic_installed, install_gimp_appimage, install_gimp_package_manager, install_gmic_only, remove_gmic_only
from ...hardware import recommended_model_key, recommended_torch_index
from ...job import Job
from ...models import MODEL_BY_KEY, MODEL_REGISTRY, ModelSpec, model_installed, model_path
from ...photogimp import install_photogimp, photogimp_installed, remove_photogimp, repair_desktop_integration
from ...plan import InstallPlan, PlannedAction, WizardStep
from ...plugins import batcher_installed, install_batcher, install_segany_plugin, remove_batcher, remove_segany_plugin, segany_plugin_installed, write_segany_plugin_settings
from ...sam3 import download_sam3, remove_sam3, sam3_failure_message
from ...sam_backend import backend_ready, install_sam3_transformers, install_sam_backend, remove_sam_backend, venv_exists, write_sam_info
from ..dialogs import show_snackbar, themed_confirm, themed_info
from ..helpers import autowrap_label, flatten_entry, rating_widget
from ..icons import icon_canvas
from ..theme import ACCENT, BG, CARD_BG, DANGER, F_BODY, F_BODY_B, F_H3, F_ITEM_TITLE, F_SECTION, F_SMALL, F_SMALL_B, SUCCESS, TEXT, TEXT_MUTED
from ..widgets import RoundedButton, RoundedCard, ScrollableFrame, bind_click_recursive, callout
from typing import Optional
import os
import shutil
import webbrowser


class WizardPages:
    _WIZARD_RENDERERS = {
        "gimp": "_wizard_render_gimp",
        "photogimp": "_wizard_render_photogimp",
        "gmic": "_wizard_render_gmic",
        "sam": "_wizard_render_sam",
        "batcher": "_wizard_render_batcher",
        "review": "_wizard_render_review",
    }

    # Which wizard page owns a given plan key, so Review's rows can jump
    # straight back to the page that queued them.
    _WIZARD_KEY_PREFIXES = (
        ("gimp_install_", "gimp"),
        ("photogimp:", "photogimp"),
        ("gmic:", "gmic"),
        ("sam_setup:", "sam"),
        ("sam_model:", "sam"),
        ("sam3:", "sam"),
        ("batcher:", "batcher"),
    )

    def show_wizard(self):
        self.plan = InstallPlan()
        default_choice = list(TORCH_INDEX_URLS.keys())[
            list(TORCH_INDEX_URLS.values()).index(recommended_torch_index(self.hw))]
        self.torch_choice = tk.StringVar(value=default_choice)
        self.hf_token_var = tk.StringVar()
        self.wizard_steps = self._build_wizard_steps()
        self.wizard_index = 0
        self._render_wizard_step()

    def _build_wizard_steps(self) -> list[WizardStep]:
        steps = []
        if not (gimp_native_installed() or appimage_present()):
            steps.append(WizardStep("gimp", "GIMP (prerequisite)", prerequisite=True))
        steps.append(WizardStep("photogimp", "PhotoGIMP"))
        steps.append(WizardStep("gmic", "G'MIC"))
        steps.append(WizardStep("sam", "SAM (segmentation models)"))
        steps.append(WizardStep("batcher", "Batcher"))
        steps.append(WizardStep("review", "Review & install"))
        return steps

    def _wizard_can_advance(self) -> bool:
        step = self.wizard_steps[self.wizard_index]
        if step.key == "gimp":
            return self.plan.has("gimp_install_pm") or self.plan.has("gimp_install_appimage")
        return True

    def _wizard_advance(self):
        if not self._wizard_can_advance():
            return
        self.wizard_index += 1
        self._render_wizard_step()

    def _wizard_back(self):
        if self.wizard_index == 0:
            if len(self.plan) and not themed_confirm(
                    self.root, "Leave setup", "Discard your selections and go back to the start screen?"):
                return
            self.show_landing()
            return
        self.wizard_index -= 1
        self._render_wizard_step()

    def _wizard_jump_to_step(self, step_key: str):
        for i, step in enumerate(self.wizard_steps):
            if step.key == step_key:
                self.wizard_index = i
                self._render_wizard_step()
                return

    def _wizard_step_key_for_action(self, key: str) -> str:
        for prefix, step_key in self._WIZARD_KEY_PREFIXES:
            if key.startswith(prefix):
                return step_key
        return "review"

    def _wizard_toggle_and_advance(self, key: str, label: str, kind: str, run, *, advance: bool):
        """Toggle one PlannedAction in/out of the plan. Picking an action
        on a single-decision page (GIMP/PhotoGIMP/G'MIC/Batcher) moves
        straight on to the next page, like a normal installer; un-picking
        it (or toggling on a multi-item page like SAM, where jumping away
        after every click would make it impossible to pick more than one
        thing) just refreshes this page in place — a cheap, flicker-free
        partial redraw, not a full-screen rebuild."""
        now_queued = self.plan.toggle(PlannedAction(key=key, label=label, kind=kind, run=run))
        if advance and now_queued:
            self._wizard_advance()
        else:
            self._refresh_wizard_body()

    def _render_wizard_step(self):
        self.current_screen = "wizard"
        for w in self.root_frame.winfo_children():
            w.destroy()
        step = self.wizard_steps[self.wizard_index]

        outer = tk.Frame(self.root_frame, bg=BG)
        outer.pack(fill="both", expand=True)

        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x", padx=26, pady=(16, 0))
        tk.Label(top, text=step.title, bg=BG, fg=TEXT, font=F_H3).pack(side="left")
        tk.Label(top, text=f"Step {self.wizard_index + 1} of {len(self.wizard_steps)}", bg=BG,
                 fg=TEXT_MUTED, font=F_BODY).pack(side="right")

        nav = tk.Frame(outer, bg=BG)
        nav.pack(fill="x", padx=26, pady=(10, 16), side="bottom")
        RoundedButton(nav, "← Back", variant="secondary", width=110, command=self._wizard_back).pack(
            side="left")
        self._wizard_next_btn = None
        if step.key != "review":
            self._wizard_next_btn = RoundedButton(nav, "Next →", variant="primary", width=140,
                                                   command=self._wizard_advance)
            self._wizard_next_btn.pack(side="right")
            self._wizard_next_btn.set_enabled(self._wizard_can_advance())
            if not step.prerequisite:
                RoundedButton(nav, "Skip →", variant="secondary", width=110,
                              command=self._wizard_advance).pack(side="right", padx=(0, 8))

        self._wizard_scroller = ScrollableFrame(outer)
        self._wizard_scroller.pack(fill="both", expand=True, padx=26, pady=(6, 0))
        self._wizard_body_parent = self._wizard_scroller.inner
        self._refresh_wizard_body()

    def _refresh_wizard_body(self):
        """Re-render only the current page's content, in place — used for
        every toggle click so a selection never causes the whole screen
        (top bar, nav bar, scrollbar) to flash and rebuild."""
        parent = self._wizard_body_parent
        for w in parent.winfo_children():
            w.destroy()
        step = self.wizard_steps[self.wizard_index]
        getattr(self, self._WIZARD_RENDERERS[step.key])(parent)
        if self._wizard_next_btn is not None and self._wizard_next_btn.winfo_exists():
            self._wizard_next_btn.set_enabled(self._wizard_can_advance())

    def _status_row(self, body, ok: bool, text: str):
        row = tk.Frame(body, bg=CARD_BG)
        row.pack(fill="x", pady=(0, 10))
        icon_canvas(row, "check" if ok else "x", color=SUCCESS if ok else TEXT_MUTED, size=16,
                    bg=CARD_BG).pack(side="left", padx=(0, 8))
        autowrap_label(row, text, fg=TEXT, bg=CARD_BG, font=F_BODY).pack(side="left", fill="x",
                                                                                 expand=True)

    def _wizard_toggle_card(self, parent, *, key: str, installed: bool, status_text: str, install_label: str,
                             install_run, uninstall_run, uninstall_label: str = "Uninstall",
                             install_enabled: bool = True, disabled_reason: Optional[str] = None,
                             advance: bool = True, extra=None):
        """One reusable card covering every single-decision component page
        (PhotoGIMP, G'MIC, Batcher):
        not installed -> one green toggle that queues/unqueues Install;
        installed -> one red toggle that queues/unqueues Uninstall.
        Exactly one button, so there's never a second, greyed-out one
        sitting next to it — just a ✓ once it's queued."""
        card = RoundedCard(parent)
        card.pack(fill="x", pady=(0, 10))
        body = card.body
        self._status_row(body, installed, status_text)
        if extra:
            extra(body)
        btn_row = tk.Frame(body, bg=CARD_BG)
        btn_row.pack(fill="x", pady=(6, 0))
        if installed:
            remove_key = f"{key}:remove"
            queued = self.plan.has(remove_key)
            RoundedButton(
                btn_row, uninstall_label + (" ✓" if queued else ""), icon="trash", variant="danger", width=220,
                command=lambda: self._wizard_toggle_and_advance(
                    remove_key, f"Remove {install_label}", "remove", uninstall_run, advance=advance),
            ).pack(side="left")
        else:
            install_key = f"{key}:install"
            queued = self.plan.has(install_key)
            btn = RoundedButton(
                btn_row, install_label + (" ✓" if queued else ""), icon="install", variant="success", width=220,
                command=lambda: self._wizard_toggle_and_advance(
                    install_key, install_label, "install", install_run, advance=advance),
            )
            btn.pack(side="left")
            btn.set_enabled(install_enabled or queued)
            if not (install_enabled or queued) and disabled_reason:
                callout(body, disabled_reason, "warn")
        card.finalize()

    # -- GIMP (prerequisite; mandatory, exclusive choice of method) -------

    def _wizard_render_gimp(self, parent):
        native = gimp_native_installed()
        appimg = appimage_present()
        distro = detect_distro()
        card = RoundedCard(parent)
        card.pack(fill="x", pady=(0, 4))
        body = card.body
        self._status_row(body, native, f"Native package ({distro or 'no supported distro detected'})"
                                        + (" — installed" if native else " — not installed"))
        self._status_row(body, appimg, f"AppImage in {APPIMAGE_DIR}"
                                        + (" — installed" if appimg else " — not installed"))

        btn_row = tk.Frame(body, bg=CARD_BG)
        btn_row.pack(fill="x", pady=(6, 0))
        pm_selected = self.plan.has("gimp_install_pm")
        ai_selected = self.plan.has("gimp_install_appimage")
        pm_btn = RoundedButton(
            btn_row, "Install via package manager" + (" ✓" if pm_selected else ""), icon="install",
            variant="success", width=270, command=lambda: self._wizard_pick_gimp_method("pm"))
        pm_btn.pack(side="left", padx=(0, 8))
        pm_btn.set_enabled(bool(distro))
        ai_btn = RoundedButton(
            btn_row, "Install AppImage" + (" ✓" if ai_selected else ""), icon="install",
            variant="success", width=210, command=lambda: self._wizard_pick_gimp_method("appimage"))
        ai_btn.pack(side="left")
        if not distro:
            callout(body, "No supported distribution detected (arch, debian, ubuntu, fedora, opensuse) — "
                           "use the AppImage instead.", "warn")
        callout(body, "GIMP is a prerequisite for everything else, so this page can't be skipped — "
                      "pick one of the two methods above to continue.", "info")
        card.finalize()

    def _wizard_pick_gimp_method(self, method: str):
        self.plan.discard("gimp_install_pm")
        self.plan.discard("gimp_install_appimage")
        if method == "pm":
            action = PlannedAction("gimp_install_pm", "Install GIMP (package manager)", "install",
                                    lambda job: install_gimp_package_manager(job, include_gmic=False))
        else:
            action = PlannedAction("gimp_install_appimage", "Install GIMP (AppImage)", "install",
                                    lambda job: install_gimp_appimage(job))
        self.plan.add(action)
        self._wizard_advance()

    # -- PhotoGIMP ---------------------------------------------------------

    def _wizard_render_photogimp(self, parent):
        installed = photogimp_installed()

        def extra(body):
            autowrap_label(body, "Also fixes the taskbar/window icon showing a generic icon instead of "
                                  "PhotoGIMP's — every (re)install regenerates that desktop-file fix.",
                           fg=TEXT_MUTED, bg=CARD_BG, font=F_SMALL).pack(anchor="w", fill="x", pady=(0, 10))
            if installed:
                RoundedButton(body, "Fix taskbar icon now", icon="refresh", variant="secondary", width=200,
                              command=self._repair_photogimp_desktop).pack(anchor="w", pady=(0, 8))

        self._wizard_toggle_card(
            parent, key="photogimp", installed=installed,
            status_text="Icons, shortcuts, splash screen, UI layout"
                         + (" — installed" if installed else " — not installed"),
            install_label="Install PhotoGIMP",
            install_run=lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0]),
            uninstall_run=lambda job: remove_photogimp(job),
            extra=extra,
        )

    def _repair_photogimp_desktop(self):
        def task(job: Job):
            repair_desktop_integration(job)

        def done():
            if self.current_screen == "wizard":
                self._refresh_wizard_body()
            show_snackbar(self, "Desktop entry fixed — restart GIMP and re-pin it", tone="ok")

        self.run_in_background(task, on_done=done)

    # -- G'MIC ---------------------------------------------------------------

    def _wizard_render_gmic(self, parent):
        installed = gmic_installed()
        available = gmic_available_on_this_release()
        self._wizard_toggle_card(
            parent, key="gmic", installed=installed,
            status_text="Extra filter collection for GIMP" + (" — installed" if installed else " — not installed"),
            install_label="Install G'MIC",
            install_run=lambda job: install_gmic_only(job),
            uninstall_run=lambda job: remove_gmic_only(job),
            install_enabled=available,
            disabled_reason=(None if available else
                              f"No G'MIC package on this distribution release — see {GMIC_DOWNLOAD_PAGE} "
                              "for a manual build."),
        )

    # -- SAM: one setup action (plug-in + backend) + models + SAM 3.1 -------
    # The plug-in and the Python backend are two files on disk from the
    # user's point of view — "SAM works or it doesn't" — so they're one
    # queueable action, not two separate questions. Its single run()
    # re-checks what's actually missing at execution time and only does
    # that, so the very same button is correct whether nothing is
    # installed yet, only the backend is broken, or everything is already
    # fine (in which case the page offers Uninstall instead).
    #
    # Every widget on this page is built exactly once per visit and then
    # only ever has its text/enabled state *updated* afterwards (never
    # destroyed and rebuilt) — refresh_sam_page() below is the one place
    # that happens, which is what keeps this page from flashing on every
    # click the way a full-page rebuild would.

    def _sam_setup_install_run(self):
        def run(job: Job):
            if not segany_plugin_installed():
                job.log("Installing the SAM plug-in...")
                install_segany_plugin(job)
            else:
                job.log("SAM plug-in already installed.")
            if not backend_ready():
                job.log("Setting up the SAM Python backend...")
                install_sam_backend(job, TORCH_INDEX_URLS[self.torch_choice.get()])
            else:
                job.log("SAM Python backend already ready.")
        return run

    @staticmethod
    def _sam_setup_remove_run(job: Job):
        remove_segany_plugin(job)
        remove_sam_backend(job)

    @staticmethod
    def _sam_model_install_run(spec: ModelSpec):
        def run(job: Job):
            dest = model_path(spec)
            if os.path.isfile(dest):
                job.log(f"{spec.label} already downloaded at {dest}")
                return
            if job.download(spec.url, dest, job.cancel_event):
                write_segany_plugin_settings(spec)
                write_sam_info([spec.key])
        return run

    @staticmethod
    def _sam_model_remove_run(spec: ModelSpec):
        def run(job: Job):
            dest = model_path(spec)
            try:
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                elif os.path.isfile(dest):
                    os.remove(dest)
                job.log(f"Removed {dest}")
            except Exception as e:
                job.log(f"ERROR removing {dest}: {e}")
        return run

    def _wizard_render_sam(self, parent):
        plugin_ok = segany_plugin_installed()
        ready = backend_ready()
        exists = venv_exists()
        fully_ready = plugin_ok and ready
        setup_install_key, setup_remove_key = "sam_setup:install", "sam_setup:remove"

        def sam_present_after() -> bool:
            if fully_ready:
                return not self.plan.has(setup_remove_key)
            return self.plan.has(setup_install_key)

        model_widgets: list[tuple] = []       # (button, spec, installed)
        queue_all_buttons: list = []

        # -- combined plug-in + backend card --
        card = RoundedCard(parent)
        card.pack(fill="x", pady=(0, 10))
        body = card.body
        self._status_row(body, plugin_ok, "SAM plug-in files"
                          + (" — installed" if plugin_ok else " — not installed"))
        self._status_row(body, ready, "Python backend (PyTorch venv)"
                          + (" — ready" if ready else " — not ready"))
        if ready:
            callout(body, f"Ready at {VENV_DIR}", "ok")
        elif exists:
            callout(body, "A virtualenv exists but PyTorch isn't importable — Repair will retry it.", "warn")
        else:
            callout(body, "Not set up yet.", "warn")
        tk.Label(body, text="PyTorch build", bg=CARD_BG, fg=TEXT, font=F_BODY_B).pack(
            anchor="w", pady=(8, 6))
        combo = ttk.Combobox(body, textvariable=self.torch_choice, values=list(TORCH_INDEX_URLS.keys()),
                              state="readonly", width=34, font=F_BODY)
        combo.pack(anchor="w", pady=(0, 6))
        flatten_entry(combo)

        btn_row = tk.Frame(body, bg=CARD_BG)
        btn_row.pack(fill="x", pady=(6, 0))
        if fully_ready:
            setup_label, setup_kind, setup_key = "Uninstall SAM (plug-in + backend + all models)", "remove", setup_remove_key
            setup_run = self._sam_setup_remove_run
            setup_variant = "danger"
        else:
            setup_label = "Install SAM" if not (plugin_ok or exists) else "Repair SAM setup"
            setup_kind, setup_key = "install", setup_install_key
            setup_run = self._sam_setup_install_run()
            setup_variant = "success"
        setup_btn = RoundedButton(btn_row, setup_label, icon=("trash" if fully_ready else "install"),
                                   variant=setup_variant, width=340)
        setup_btn.pack(side="left")

        def toggle_setup():
            self.plan.toggle(PlannedAction(setup_key, setup_label, setup_kind, setup_run))
            refresh_sam_page()

        setup_btn.command = toggle_setup

        # -- models, by family --
        autowrap_label(
            parent,
            "Quality/Speed are rough 1-5 estimates, comparable within a family. Already-downloaded models "
            "are never a checkbox again — Remove just queues their deletion for the final install step.",
            fg=TEXT_MUTED, bg=BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(6, 10))
        gate_note = callout(parent, "Models need the SAM setup above first.", "warn")
        if sam_present_after():
            gate_note.pack_forget()

        rec_key = recommended_model_key(self.hw)
        for family in ("SAM1", "SAM2"):
            fam_card = RoundedCard(parent)
            fam_card.pack(fill="x", pady=(0, 10))
            head = tk.Frame(fam_card.body, bg=CARD_BG)
            head.pack(fill="x", pady=(0, 4))
            tk.Label(head, text=family, bg=CARD_BG, fg=ACCENT, font=F_SECTION).pack(side="left")
            queue_all_btn = RoundedButton(head, "Queue all missing", icon="install", variant="secondary",
                                           width=170)
            queue_all_btn.pack(side="right")
            queue_all_buttons.append(queue_all_btn)

            for spec in [m for m in MODEL_REGISTRY if m.family == family]:
                row = RoundedCard(fam_card.body, pad=14, radius=16)
                row.pack(fill="x", pady=6)
                rbody = row.body
                top = tk.Frame(rbody, bg=CARD_BG)
                top.pack(fill="x")
                left = tk.Frame(top, bg=CARD_BG)
                left.pack(side="left", fill="x", expand=True)
                name_row = tk.Frame(left, bg=CARD_BG)
                name_row.pack(anchor="w")
                tk.Label(name_row, text=spec.label, bg=CARD_BG, fg=TEXT, font=F_ITEM_TITLE).pack(
                    side="left")
                tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=F_SMALL).pack(
                    side="left")
                if spec.key == rec_key:
                    tk.Label(name_row, text="  ★ Recommended", bg=CARD_BG, fg=ACCENT,
                             font=F_SMALL_B).pack(side="left")
                rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

                installed = model_installed(spec)
                right = tk.Frame(top, bg=CARD_BG)
                right.pack(side="right")
                if installed:
                    btn = RoundedButton(right, "Remove", icon="trash", variant="danger", width=160)
                else:
                    btn = RoundedButton(right, "Add to plan", icon="install", variant="success", width=160)
                btn.pack(side="left")
                model_widgets.append((btn, spec, installed))
                row.finalize()
            fam_card.finalize()

        def bind_model_row(btn, spec, installed):
            install_key, remove_key = f"sam_model:{spec.key}:install", f"sam_model:{spec.key}:remove"
            if installed:
                btn.command = lambda: (
                    self.plan.toggle(PlannedAction(remove_key, f"Remove {spec.label}", "remove",
                                                    self._sam_model_remove_run(spec))),
                    refresh_sam_page())
            else:
                btn.command = lambda: (
                    self.plan.toggle(PlannedAction(install_key, f"Download {spec.label}", "install",
                                                    self._sam_model_install_run(spec))),
                    refresh_sam_page())

        for btn, spec, installed in model_widgets:
            bind_model_row(btn, spec, installed)

        def queue_all(family):
            missing = [m for m in MODEL_REGISTRY if m.family == family and not model_installed(m)]
            if not missing:
                themed_info(self.root, "Nothing to do", f"All {family} models are already installed.")
                return
            for spec in missing:
                key = f"sam_model:{spec.key}:install"
                if not self.plan.has(key):
                    self.plan.add(PlannedAction(key, f"Download {spec.label}", "install",
                                                 self._sam_model_install_run(spec)))
            refresh_sam_page()

        families = ("SAM1", "SAM2")
        for fam, qbtn in zip(families, queue_all_buttons):
            qbtn.command = lambda fam=fam: queue_all(fam)

        sam3_widgets = self._wizard_render_sam3(parent, sam_present_after)

        def refresh_sam_page():
            present = sam_present_after()
            if fully_ready:
                setup_btn.set_text(setup_label + (" ✓" if self.plan.has(setup_remove_key) else ""))
            else:
                setup_btn.set_text(setup_label + (" ✓" if self.plan.has(setup_install_key) else ""))
            if present:
                gate_note.pack_forget()
            else:
                gate_note.pack(fill="x", pady=(4, 12))
            for btn, spec, installed in model_widgets:
                if installed:
                    q = self.plan.has(f"sam_model:{spec.key}:remove")
                    btn.set_text("Remove" + (" ✓" if q else ""))
                else:
                    q = self.plan.has(f"sam_model:{spec.key}:install")
                    btn.set_text("Add to plan" + (" ✓" if q else ""))
                    btn.set_enabled(present or q)
            for qbtn in queue_all_buttons:
                qbtn.set_enabled(present)
            sam3_widgets.refresh(present)

        refresh_sam_page()

    # -- SAM 3.1 (gated on Hugging Face) -------------------------------------

    class _Sam3Widgets:
        """Tiny bundle returned so the SAM page's refresh_sam_page() can
        update SAM3's enabled state (it depends on sam_present_after(),
        which the setup card owns) without rebuilding anything."""
        def __init__(self, refresh_fn):
            self._refresh_fn = refresh_fn

        def refresh(self, present: bool):
            self._refresh_fn(present)

    def _wizard_render_sam3(self, parent, sam_present_after):
        spec = MODEL_BY_KEY["sam3"]
        installed = model_installed(spec)
        card = RoundedCard(parent)
        card.pack(fill="x", pady=(0, 10))
        body = card.body

        top = tk.Frame(body, bg=CARD_BG)
        top.pack(fill="x")
        left = tk.Frame(top, bg=CARD_BG)
        left.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(left, bg=CARD_BG)
        name_row.pack(anchor="w")
        tk.Label(name_row, text=f"{spec.label} (SAM3)", bg=CARD_BG, fg=TEXT, font=F_ITEM_TITLE).pack(
            side="left")
        tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=F_SMALL).pack(side="left")
        rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

        install_key, remove_key = "sam3:install", "sam3:remove"

        autowrap_label(
            body, f"Gated on Hugging Face ({SAM3_HF_REPO_ID}) — request access, wait for approval, then "
                  "paste a READ token below. The token is only checked against the repo once the plan "
                  "actually runs, so queuing it now is free.",
            fg=TEXT_MUTED, bg=CARD_BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(12, 14))

        row1 = tk.Frame(body, bg=CARD_BG)
        row1.pack(fill="x", pady=(0, 10))
        RoundedButton(row1, "Request access on Hugging Face", icon="link", variant="secondary", width=270,
                      command=lambda: webbrowser.open(SAM3_HF_PAGE)).pack(side="left")
        transformers_key = "sam3:transformers"
        transformers_btn = RoundedButton(row1, "Install/upgrade transformers", icon="box", variant="success",
                                          width=230)
        transformers_btn.pack(side="left", padx=8)

        def toggle_transformers():
            self.plan.toggle(PlannedAction(transformers_key, "Install/upgrade transformers", "install",
                                            lambda job: install_sam3_transformers(job)))
            transformers_btn.set_text("Install/upgrade transformers"
                                       + (" ✓" if self.plan.has(transformers_key) else ""))

        transformers_btn.command = toggle_transformers

        row2 = tk.Frame(body, bg=CARD_BG)
        row2.pack(fill="x")
        tk.Label(row2, text="HF token", bg=CARD_BG, fg=TEXT, font=F_BODY_B).pack(side="left")
        hf_entry = ttk.Entry(row2, textvariable=self.hf_token_var, show="*", width=30, font=F_BODY)
        hf_entry.pack(side="left", padx=8, ipady=3)
        flatten_entry(hf_entry)

        gate_note = callout(body, "Needs the SAM setup above first.", "warn")

        if installed:
            sam3_btn = RoundedButton(row2, "Remove", icon="trash", variant="danger", width=130)
            sam3_btn.pack(side="left")

            def toggle_sam3():
                self.plan.toggle(PlannedAction(remove_key, "Remove SAM 3.1", "remove",
                                                lambda job: remove_sam3(job)))
                sam3_btn.set_text("Remove" + (" ✓" if self.plan.has(remove_key) else ""))

            sam3_btn.command = toggle_sam3
            gate_note.pack_forget()

            def refresh(_present: bool):
                pass
        else:
            sam3_btn = RoundedButton(
                row2, "Add to plan", icon="install", variant="success", width=140,
                on_blocked=lambda: show_snackbar(self, "Enter a Hugging Face token first", tone="warn"))
            sam3_btn.pack(side="left")

            def token_entered() -> bool:
                return bool(self.hf_token_var.get().strip())

            def toggle_sam3():
                self.plan.toggle(PlannedAction(install_key, "Download SAM 3.1", "install",
                                                lambda job: self._run_sam3_download(job)))
                sam3_btn.set_text("Add to plan" + (" ✓" if self.plan.has(install_key) else ""))

            sam3_btn.command = toggle_sam3

            def refresh(present: bool):
                queued = self.plan.has(install_key)
                sam3_btn.set_enabled(present and (queued or token_entered()))
                if present:
                    gate_note.pack_forget()
                else:
                    gate_note.pack(fill="x", pady=(4, 12))

            trace_id = self.hf_token_var.trace_add("write", lambda *_a: refresh(sam_present_after()))
            sam3_btn.bind("<Destroy>", lambda _e, tid=trace_id: self.hf_token_var.trace_remove("write", tid))

        refresh(sam_present_after())
        card.finalize()
        return self._Sam3Widgets(refresh)

    def _run_sam3_download(self, job: Job):
        token = self.hf_token_var.get().strip()
        if not token:
            job.log("No Hugging Face token was entered — skipping SAM 3.1.")
            return
        ok, tag = download_sam3(job, token)
        if not ok:
            job.log(sam3_failure_message(tag))

    # -- Batcher -----------------------------------------------------

    def _wizard_render_batcher(self, parent):
        installed = batcher_installed()
        self._wizard_toggle_card(
            parent, key="batcher", installed=installed,
            status_text="Batch image processing / export layers"
                         + (" — installed" if installed else " — not installed"),
            install_label="Install Batcher",
            install_run=lambda job: install_batcher(job),
            uninstall_run=lambda job: remove_batcher(job),
        )

    # -- Review & install --------------------------------------------------

    def _wizard_render_review(self, parent):
        if len(self.plan) == 0:
            card = RoundedCard(parent)
            card.pack(fill="x")
            tk.Label(card.body, text="Nothing queued yet — go back and pick at least one action.",
                     bg=CARD_BG, fg=TEXT_MUTED, font=F_BODY).pack(anchor="w")
            card.finalize()
            return

        # SAM models are queued one-by-one so each page can show its own
        # state, but a dozen "Download vit_b" / "Download vit_l" lines
        # here would just be noise — collapse them into one summary row.
        sam_installs = [a for a in self.plan if a.key.startswith("sam_model:") and a.kind == "install"]
        sam_removes = [a for a in self.plan if a.key.startswith("sam_model:") and a.kind == "remove"]
        grouped_keys = {a.key for a in sam_installs + sam_removes}
        other_actions = [a for a in self.plan if a.key not in grouped_keys]

        def add_row(label: str, kind: str, step_key: str, keys: list[str]):
            row = RoundedCard(parent, pad=14, radius=14)
            row.pack(fill="x", pady=5)
            line = tk.Frame(row.body, bg=CARD_BG)
            line.pack(fill="x")
            icon_canvas(line, "trash" if kind == "remove" else "install",
                        color=DANGER if kind == "remove" else SUCCESS, size=16,
                        bg=CARD_BG).pack(side="left", padx=(0, 10))
            tk.Label(line, text=label, bg=CARD_BG, fg=TEXT, font=F_BODY_B).pack(
                side="left", fill="x", expand=True)
            trash_btn = RoundedButton(line, "", icon="trash", variant="secondary", width=40,
                                       command=lambda: self._wizard_discard_many(keys))
            trash_btn.pack(side="right")
            row.finalize()
            bind_click_recursive(row, lambda sk=step_key: self._wizard_jump_to_step(sk), skip=(trash_btn,))

        for action in other_actions:
            add_row(action.label, action.kind, self._wizard_step_key_for_action(action.key), [action.key])
        if sam_installs:
            add_row(f"Download {len(sam_installs)} SAM model" + ("s" if len(sam_installs) != 1 else ""),
                    "install", "sam", [a.key for a in sam_installs])
        if sam_removes:
            add_row(f"Remove {len(sam_removes)} SAM model" + ("s" if len(sam_removes) != 1 else ""),
                    "remove", "sam", [a.key for a in sam_removes])

        RoundedButton(parent, f"Proceed to installation ({len(self.plan)})", icon="bolt", variant="primary",
                      width=320, height=44, command=self._wizard_start_install).pack(anchor="w", pady=(14, 0))

    def _wizard_discard_many(self, keys: list[str]):
        for key in keys:
            self.plan.discard(key)
        self._refresh_wizard_body()

    def _wizard_start_install(self):
        self.show_install_progress(list(self.plan))
