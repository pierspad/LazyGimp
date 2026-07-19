"""The paginated setup wizard (GIMP > PhotoGIMP > G'MIC > SAM >
Batcher > Review). Every page only queues PlannedActions into
self.plan; nothing here touches disk."""

from __future__ import annotations

from ...compat import ctk, tk
from ...constants import GMIC_DOWNLOAD_PAGE
from ...distro import detect_distro
from ...gimp_detect import find_gimp_binary, find_gimp_command
from ...gimp_install import appimage_present, gimp_native_installed, gmic_available_on_this_release, gmic_installed, install_gimp_appimage, install_gimp_package_manager, install_gmic_only, remove_gmic_only
from ...hardware import recommended_model_key, recommended_torch_index
from ...job import Job
from ...models import MODEL_BY_KEY, MODEL_REGISTRY, ModelSpec, model_installed, model_path
from ...photogimp import install_photogimp, photogimp_installed, remove_photogimp, repair_desktop_integration
from ...plan import InstallPlan, PlannedAction, WizardStep
from ...plugins import batcher_installed, install_batcher, install_segany_plugin, remove_batcher, remove_segany_plugin, segany_plugin_installed, write_segany_plugin_settings
from ...sam3 import SAM3_HF_PAGE, SAM3_HF_REPO_ID, download_sam3, remove_sam3, sam3_failure_message
from ...sam_backend import TORCH_INDEX_URLS, backend_ready, install_sam3_transformers, install_sam_backend, remove_sam_backend, write_sam_info
from ..dialogs import show_snackbar, themed_confirm, themed_info
from ..helpers import autowrap_label, rating_widget
from ..icons import icon_canvas
from ..theme import ACCENT, BG, CARD_BG, CARD_BORDER, DANGER, DISABLED_BG, DISABLED_TEXT, F_BODY, F_BODY_B, F_H3, F_ITEM_TITLE, F_SECTION, F_SMALL, F_SMALL_B, FIELD_BG, SECONDARY_HOVER, SUCCESS, TEXT, TEXT_MUTED, F_CARD_TITLE, WARNING
from ..widgets import RoundedButton, RoundedCard, ScrollableFrame, bind_click_recursive, callout
from typing import Optional
import os
import shutil
import webbrowser


class WizardPages:
    _WIZARD_RENDERERS = {
        "gimp": "_wizard_render_gimp",
        "components": "_wizard_render_components",
        "sam": "_wizard_render_sam",
        "review": "_wizard_render_review",
    }

    # Which wizard page owns a given plan key, so Review's rows can jump
    # straight back to the page that queued them.
    _WIZARD_KEY_PREFIXES = (
        ("gimp_install_", "gimp"),
        ("photogimp:", "components"),
        ("gmic:", "components"),
        ("sam_setup:", "sam"),
        ("sam_model:", "sam"),
        ("sam3:", "sam"),
        ("batcher:", "components"),
    )

    def show_wizard(self):
        self.plan = InstallPlan()
        
        # Preselect defaults on startup
        if not (gimp_native_installed() or appimage_present() or find_gimp_binary()):
            if detect_distro():
                self.plan.add(PlannedAction(
                    "gimp_install_pm", "Install GIMP (package manager)", "install",
                    lambda job: install_gimp_package_manager(job, include_gmic=False)
                ))

        if not photogimp_installed():
            self.plan.add(PlannedAction(
                "photogimp:install", "Install PhotoGIMP", "install",
                lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0])
            ))

        if gmic_available_on_this_release() and not gmic_installed():
            self.plan.add(PlannedAction(
                "gmic:install", "Install G'MIC", "install",
                lambda job: install_gmic_only(job)
            ))

        spec = MODEL_BY_KEY["sam2_hiera_small"]
        if not model_installed(spec):
            self.plan.add(PlannedAction(
                f"sam_model:{spec.key}:install", f"Download {spec.label}", "install",
                self._sam_model_install_run(spec)
            ))
            if not backend_ready() or not segany_plugin_installed():
                self.plan.add(PlannedAction(
                    "sam_setup:install", "Install SAM backend", "install",
                    self._sam_setup_install_run()
                ))

        default_choice = list(TORCH_INDEX_URLS.keys())[
            list(TORCH_INDEX_URLS.values()).index(recommended_torch_index(self.hw))]
        self.torch_choice = tk.StringVar(value=default_choice)
        self.hf_token_var = tk.StringVar()
        self.wizard_steps = self._build_wizard_steps()
        self.wizard_index = 0
        self._prev_wizard_index = 0
        self._current_wizard_frame = None
        self._wizard_animating = False
        self._wizard_cards = {}
        self._review_rows_discard_commands = []
        self._wizard_page_cache = {}
        self._component_card_refreshers = []
        self._render_wizard_step()
        self.root.after(100, self._pre_render_hidden_pages)

    def _build_wizard_steps(self) -> list[WizardStep]:
        steps = []
        if not (gimp_native_installed() or appimage_present() or find_gimp_binary()):
            steps.append(WizardStep("gimp", "GIMP (prerequisite)", prerequisite=True))
        steps.append(WizardStep("components", "Select which plugin you want to add"))
        steps.append(WizardStep("sam", "SAM (segmentation models)"))
        steps.append(WizardStep("review", "Review & install"))
        return steps

    def _wizard_can_advance(self) -> bool:
        step = self.wizard_steps[self.wizard_index]
        if step.key == "gimp":
            return self.plan.has("gimp_install_pm") or self.plan.has("gimp_install_appimage")
        return True

    def _wizard_advance(self):
        if getattr(self, "_wizard_animating", False):
            return
        if not self._wizard_can_advance():
            return
        self.wizard_index += 1
        self._render_wizard_step()

    def _wizard_back(self):
        if getattr(self, "_wizard_animating", False):
            return
        if self.wizard_index == 0:
            if len(self.plan) and not themed_confirm(
                    self.root, "Leave setup", "Discard your selections and go back to the start screen?"):
                return
            self._current_wizard_frame = None
            self.show_landing()
            return
        self.wizard_index -= 1
        self._render_wizard_step()

    def _wizard_jump_to_step(self, step_key: str):
        if getattr(self, "_wizard_animating", False):
            return
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
        step = self.wizard_steps[self.wizard_index]

        # 1. Initialize outer skeleton if needed
        if not self._current_wizard_frame or not self._current_wizard_frame.winfo_exists():
            for w in self.root_frame.winfo_children():
                w.destroy()
            
            outer = tk.Frame(self.root_frame, bg=BG)
            outer.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._current_wizard_frame = outer
            
            self._wizard_header_frame = tk.Frame(outer, bg=BG)
            self._wizard_header_frame.pack(fill="x", padx=26, pady=(16, 0), side="top")
            
            self._wizard_title_label = tk.Label(self._wizard_header_frame, bg=BG, fg=TEXT, font=F_H3)
            self._wizard_title_label.pack(side="left")
            
            self._wizard_step_label = tk.Label(self._wizard_header_frame, bg=BG, fg=TEXT_MUTED, font=F_BODY)
            self._wizard_step_label.pack(side="right")
            
            self._wizard_nav_frame = tk.Frame(outer, bg=BG)
            self._wizard_nav_frame.pack(fill="x", padx=26, pady=(10, 16), side="bottom")
            
            self._wizard_middle_frame = tk.Frame(outer, bg=BG)
            self._wizard_middle_frame.pack(fill="both", expand=True, side="top")
            
            self._active_page_frame = None

        # 2. Update persistent header labels
        self._wizard_title_label.configure(text=step.title)
        self._wizard_step_label.configure(text=f"Step {self.wizard_index + 1} of {len(self.wizard_steps)}")

        # 3. Rebuild navigation buttons inside the fixed bottom nav frame
        for w in self._wizard_nav_frame.winfo_children():
            w.destroy()
            
        RoundedButton(self._wizard_nav_frame, "← Back [Backspace]", variant="secondary", width=160, command=self._wizard_back).pack(
            side="left")
            
        self._wizard_next_btn = None
        if step.key != "review":
            self._wizard_next_btn = RoundedButton(self._wizard_nav_frame, "Next [Enter] →", variant="primary", width=160,
                                                   command=self._wizard_advance)
            self._wizard_next_btn.pack(side="right")
            self._wizard_next_btn.set_enabled(self._wizard_can_advance())
            if not step.prerequisite:
                RoundedButton(self._wizard_nav_frame, "Skip →", variant="secondary", width=110,
                               command=self._wizard_advance).pack(side="right", padx=(0, 8))

        # 4. Get or create the page frame from cache
        if not hasattr(self, "_wizard_page_cache"):
            self._wizard_page_cache = {}

        if step.key not in self._wizard_page_cache:
            new_page = tk.Frame(self._wizard_middle_frame, bg=BG)
            if step.key in ("sam", "review"):
                scroller = ScrollableFrame(new_page)
                scroller.pack(fill="both", expand=True, padx=(26, 6), pady=(6, 0))
                self._wizard_scroller = scroller
                body_parent = scroller.inner
            else:
                body = tk.Frame(new_page, bg=BG)
                body.pack(fill="both", expand=True, padx=26, pady=(6, 0))
                body_parent = body
            self._wizard_page_cache[step.key] = (new_page, body_parent)
            self._wizard_body_parent = body_parent
            self._refresh_wizard_body()
        else:
            new_page, body_parent = self._wizard_page_cache[step.key]
            self._wizard_body_parent = body_parent

        # Refresh the page state to match current plan
        if step.key == "gimp":
            for w in body_parent.winfo_children():
                w.destroy()
            self._wizard_render_gimp(body_parent)
        elif step.key == "components":
            for fn in getattr(self, "_component_card_refreshers", []):
                try:
                    fn()
                except Exception:
                    pass
        elif step.key == "sam":
            if hasattr(self, "_refresh_sam_page_fn"):
                self._refresh_sam_page_fn()
        elif step.key == "review":
            for w in body_parent.winfo_children():
                w.destroy()
            self._wizard_render_review(body_parent)

        # 5. Slide animation inside the middle frame
        old_page = self._active_page_frame
        if old_page and old_page.winfo_exists():
            direction = "forward" if self.wizard_index > self._prev_wizard_index else "backward"
            self._animate_slide(old_page, new_page, direction)
        else:
            for w in self._wizard_middle_frame.winfo_children():
                if w is not new_page:
                    is_cached = False
                    if hasattr(self, "_wizard_page_cache"):
                        for cached_page, _ in self._wizard_page_cache.values():
                            if w == cached_page:
                                is_cached = True
                                break
                    if is_cached:
                        w.place_forget()
                    else:
                        w.destroy()
            new_page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._active_page_frame = new_page

        self._prev_wizard_index = self.wizard_index

    def _animate_slide(self, old_page, new_page, direction):
        self._wizard_animating = True
        steps = 15
        interval = 12
        
        if direction == "forward":
            start_y_new = 1.0
        else:
            start_y_new = -1.0
            
        new_page.place(relx=0, rely=start_y_new, relwidth=1, relheight=1)
        new_page.lift()
        
        def ease_out(t):
            return 1.0 - (1.0 - t) * (1.0 - t)

        def step(i):
            if not self.root.winfo_exists() or not old_page.winfo_exists() or not new_page.winfo_exists():
                self._wizard_animating = False
                return
                
            t = i / steps
            progress = ease_out(t)
            
            if direction == "forward":
                curr_y_old = -progress
                curr_y_new = 1.0 - progress
            else:
                curr_y_old = progress
                curr_y_new = -1.0 + progress
                
            old_page.place(relx=0, rely=curr_y_old, relwidth=1, relheight=1)
            new_page.place(relx=0, rely=curr_y_new, relwidth=1, relheight=1)
            
            if i < steps:
                self.root.after(interval, lambda: step(i + 1))
            else:
                is_cached = False
                if hasattr(self, "_wizard_page_cache"):
                    for cached_page, _ in self._wizard_page_cache.values():
                        if old_page == cached_page:
                            is_cached = True
                            break
                if is_cached:
                    old_page.place_forget()
                else:
                    old_page.destroy()
                new_page.place(relx=0, rely=0, relwidth=1, relheight=1)
                self._active_page_frame = new_page
                self._wizard_animating = False
                
        step(1)

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

    def _pre_render_hidden_pages(self):
        if not hasattr(self, "_wizard_page_cache"):
            self._wizard_page_cache = {}
            
        for step in self.wizard_steps:
            if step.key not in self._wizard_page_cache:
                # We can't pre-render review page with widgets, it's dynamic
                # and built on transition. We can pre-render gimp, components, sam!
                if step.key == "review":
                    continue
                
                # Check if it needs scroller
                page_frame = tk.Frame(self._wizard_middle_frame, bg=BG)
                if step.key in ("sam", "review"):
                    scroller = ScrollableFrame(page_frame)
                    scroller.pack(fill="both", expand=True, padx=(26, 6), pady=(6, 0))
                    self._wizard_scroller = scroller
                    body_parent = scroller.inner
                else:
                    body = tk.Frame(page_frame, bg=BG)
                    body.pack(fill="both", expand=True, padx=26, pady=(6, 0))
                    body_parent = body
                    
                self._wizard_page_cache[step.key] = (page_frame, body_parent)
                
                # Temporarily point self._wizard_body_parent to body_parent
                old_body = getattr(self, "_wizard_body_parent", None)
                self._wizard_body_parent = body_parent
                
                getattr(self, self._WIZARD_RENDERERS[step.key])(body_parent)
                
                if old_body:
                    self._wizard_body_parent = old_body

    def _status_row(self, body, ok: bool, text: str, icon_kind=None, icon_color=None, bg=CARD_BG):
        row = tk.Frame(body, bg=bg)
        row.pack(fill="x", pady=(0, 10))
        ik = icon_kind or ("check" if ok else "x")
        ic = icon_color or (SUCCESS if ok else TEXT_MUTED)
        canvas = icon_canvas(row, ik, color=ic, size=18, bg=bg)
        canvas.pack(side="left", padx=(0, 8))
        lbl = autowrap_label(row, text, fg=TEXT, bg=bg, font=F_BODY)
        lbl.pack(side="left", fill="x", expand=True)
        return canvas, lbl

    def _wizard_toggle_card(self, parent, *, key: str, title: str, icon_kind: str, installed: bool, description: str,
                             install_label: str, install_run, uninstall_run, uninstall_label: str = "Uninstall",
                             install_enabled: bool = True, disabled_reason: Optional[str] = None,
                             advance: bool = True, extra=None, shortcut_num: Optional[str] = None):
        if installed:
            action_key = f"{key}:remove"
            action_label = f"Remove {install_label}"
            action_kind = "remove"
            action_run = uninstall_run
        else:
            action_key = f"{key}:install"
            action_label = install_label
            action_kind = "install"
            action_run = install_run

        is_card_enabled = installed or install_enabled or self.plan.has(action_key)
        queued = self.plan.has(action_key) if is_card_enabled else False

        # Set initial colors and borders
        if is_card_enabled:
            if queued:
                card_bg = "#2e1b1d" if installed else "#152e20"
                card_hover_bg = "#3b2527" if installed else "#1e3d2c"
                active_border = DANGER if installed else SUCCESS
                active_width = 2
            else:
                card_bg = CARD_BG
                card_hover_bg = "#2f323a"
                active_border = None
                active_width = 1
        else:
            card_bg = DISABLED_BG
            card_hover_bg = DISABLED_BG
            active_border = None
            active_width = 1

        # Calculate initial status text and right icon
        if installed:
            if queued:
                status_text = "queued for removal"
                status_color = DANGER
                right_icon_kind = "trash"
                right_icon_color = DANGER
            else:
                status_text = "installed"
                status_color = SUCCESS
                right_icon_kind = "check"
                right_icon_color = SUCCESS
        else:
            if queued:
                status_text = "queued for install"
                status_color = SUCCESS
                right_icon_kind = "check"
                right_icon_color = SUCCESS
            else:
                status_text = "not installed"
                status_color = TEXT_MUTED
                right_icon_kind = "circle"
                right_icon_color = CARD_BORDER

        def on_card_click():
            if not is_card_enabled:
                show_snackbar(self, disabled_reason or "Not available", "warn")
                return
            
            # Toggle Action in plan
            now_queued = self.plan.toggle(PlannedAction(action_key, action_label, action_kind, action_run))
            
            if advance and now_queued:
                self._wizard_advance()
            else:
                # Update Next button status
                if self._wizard_next_btn is not None and self._wizard_next_btn.winfo_exists():
                    self._wizard_next_btn.set_enabled(self._wizard_can_advance())
                # Update card UI state in-place without page reload!
                update_card_ui()

        self._wizard_cards[key] = on_card_click

        def update_card_ui():
            q = self.plan.has(action_key)
            if q:
                card._bg = "#2e1b1d" if installed else "#152e20"
                card._hover_bg = "#3b2527" if installed else "#1e3d2c"
                card._active_border = DANGER if installed else SUCCESS
                card._active_width = 2
                
                # Status and Right Icon when queued
                if installed:
                    ds = "queued for removal"
                    sc = DANGER
                    rik = "trash"
                    ric = DANGER
                else:
                    ds = "queued for install"
                    sc = SUCCESS
                    rik = "check"
                    ric = SUCCESS
            else:
                card._bg = CARD_BG
                card._hover_bg = "#2f323a"
                card._active_border = None
                card._active_width = 1
                
                # Status and Right Icon when not queued
                if installed:
                    ds = "installed"
                    sc = SUCCESS
                    rik = "check"
                    ric = SUCCESS
                else:
                    ds = "not installed"
                    sc = TEXT_MUTED
                    rik = "circle"
                    ric = CARD_BORDER
            
            # Update labels
            status_label.configure(text=ds, fg=sc)
            
            # Update right canvas icon
            right_canvas.delete("all")
            from ..icons import blit_icon
            blit_icon(right_canvas, 14, 14, rik, color=ric, size=28)
            
            # Refresh card color and inner widget backgrounds
            card._update_colors()

        if not hasattr(self, "_component_card_refreshers"):
            self._component_card_refreshers = []
        self._component_card_refreshers.append(update_card_ui)

        if is_card_enabled:
            card = RoundedCard(parent, bg=card_bg, border=CARD_BORDER, command=on_card_click,
                               hover_bg=card_hover_bg, active_border=active_border, active_width=active_width, hover_border=ACCENT)
        else:
            card = RoundedCard(parent, bg=card_bg, border=CARD_BORDER)

        card.pack(fill="x", pady=(0, 14))
        body = card.body

        # Pack main row inside card body
        main_row = tk.Frame(body, bg=card_bg)
        main_row.pack(fill="both", expand=True, padx=4, pady=4)
        
        # Left frame: Large icon
        left_frame = tk.Frame(main_row, bg=card_bg)
        left_frame.pack(side="left", padx=(0, 16), fill="y")
        plugin_icon_color = ACCENT if is_card_enabled else DISABLED_TEXT
        p_icon_canvas = icon_canvas(left_frame, icon_kind, color=plugin_icon_color, size=36, bg=card_bg)
        p_icon_canvas.pack(anchor="center", expand=True)

        # Middle frame: Title, Description, and Status message
        mid_frame = tk.Frame(main_row, bg=card_bg)
        mid_frame.pack(side="left", fill="both", expand=True)
        
        title_label = tk.Label(mid_frame, text=title, bg=card_bg, fg=TEXT, font=F_CARD_TITLE, anchor="w")
        title_label.pack(anchor="w", pady=(2, 0))
        
        desc_label = autowrap_label(mid_frame, description, fg=TEXT_MUTED, bg=card_bg, font=F_SMALL)
        desc_label.pack(anchor="w", fill="x", pady=(2, 4))
        
        status_label = tk.Label(mid_frame, text=status_text, bg=card_bg, fg=status_color, font=F_BODY_B, anchor="w")
        status_label.pack(anchor="w", pady=(0, 2))
        
        # Right frame: Large checkmark/trash/circle icon
        right_frame = tk.Frame(main_row, bg=card_bg)
        right_frame.pack(side="right", padx=(16, 0), fill="y")
        
        if shortcut_num:
            tk.Label(right_frame, text=f"({shortcut_num})", bg=card_bg, fg=TEXT_MUTED, font=F_SMALL_B).pack(
                side="left", padx=(0, 10))
            
        right_canvas = icon_canvas(right_frame, right_icon_kind, color=right_icon_color, size=28, bg=card_bg)
        right_canvas.pack(side="left", anchor="center", expand=True)

        if extra:
            extra_frame = tk.Frame(body, bg=card_bg)
            extra_frame.pack(fill="x", pady=(6, 0), padx=(52, 0))
            extra(extra_frame)

        if not is_card_enabled and disabled_reason:
            callout_frame = tk.Frame(body, bg=card_bg)
            callout_frame.pack(fill="x", pady=(6, 0), padx=(52, 0))
            callout(callout_frame, disabled_reason, "warn")

        card.finalize()

    # -- GIMP (prerequisite; mandatory, exclusive choice of method) -------

    def _wizard_render_gimp(self, parent):
        native = gimp_native_installed()
        appimg = appimage_present()
        distro = detect_distro()

        pm_selected = self.plan.has("gimp_install_pm")
        ai_selected = self.plan.has("gimp_install_appimage")

        # Container to hold centered cards
        container = tk.Frame(parent, bg=BG)
        container.pack(expand=True, fill="both", pady=40)
        
        center_frame = tk.Frame(container, bg=BG)
        center_frame.place(relx=0.5, rely=0.45, anchor="center")

        # Card 1: Package Manager
        pm_card_bg = "#152e20" if pm_selected else (CARD_BG if distro else DISABLED_BG)
        pm_card_hover_bg = "#1e3d2c" if pm_selected else ("#2f323a" if distro else DISABLED_BG)
        pm_card_border = CARD_BORDER if distro else DISABLED_BG
        pm_command = (lambda: self._wizard_pick_gimp_method("pm")) if distro else None

        pm_card = RoundedCard(
            center_frame,
            bg=pm_card_bg,
            border=pm_card_border,
            command=pm_command,
            hover_bg=pm_card_hover_bg,
            active_border=SUCCESS if pm_selected else None,
            active_width=2 if pm_selected else 1,
            hover_border=ACCENT if distro else None,
            width=360,
            height=280
        )
        pm_card.pack(side="left", padx=18)
        
        # Content for Card 1
        body1 = pm_card.body
        distro_icon = distro if distro else "linux"
        icon_color = SUCCESS if (native or pm_selected) else TEXT_MUTED
        icon_canvas(body1, distro_icon, color=icon_color, size=64, bg=pm_card_bg).pack(pady=(20, 10))
        
        tk.Label(body1, text="(1)", bg=pm_card_bg, fg=TEXT_MUTED, font=F_BODY_B).pack(pady=(0, 2))
        tk.Label(body1, text="Package Manager", bg=pm_card_bg, fg=TEXT, font=F_CARD_TITLE).pack(pady=(0, 4))
        
        distro_name = distro.capitalize() if distro else "Linux"
        tk.Label(body1, text=f"Use system package manager ({distro_name})", bg=pm_card_bg, fg=TEXT_MUTED, font=F_SMALL).pack(pady=(0, 15))
        
        status_text1 = "Installed ✓" if native else "Not installed"
        status_color1 = SUCCESS if native else TEXT_MUTED
        tk.Label(body1, text=status_text1, bg=pm_card_bg, fg=status_color1, font=F_BODY_B).pack(pady=(4, 0))
        
        if not distro:
            autowrap_label(body1, "No supported distro detected", 
                           fg=WARNING, bg=pm_card_bg, font=F_SMALL, justify="center").pack(pady=(6, 0))
            
        pm_card.finalize()

        # Card 2: AppImage
        ai_card_bg = "#152e20" if ai_selected else CARD_BG
        ai_card_hover_bg = "#1e3d2c" if ai_selected else "#2f323a"
        ai_card = RoundedCard(
            center_frame,
            bg=ai_card_bg,
            border=CARD_BORDER,
            command=lambda: self._wizard_pick_gimp_method("appimage"),
            hover_bg=ai_card_hover_bg,
            active_border=SUCCESS if ai_selected else None,
            active_width=2 if ai_selected else 1,
            hover_border=ACCENT,
            width=360,
            height=280
        )
        ai_card.pack(side="left", padx=18)
        
        # Content for Card 2
        body2 = ai_card.body
        icon_color2 = SUCCESS if (appimg or ai_selected) else TEXT_MUTED
        icon_canvas(body2, "box", color=icon_color2, size=64, bg=ai_card_bg).pack(pady=(20, 10))
        
        tk.Label(body2, text="(2)", bg=ai_card_bg, fg=TEXT_MUTED, font=F_BODY_B).pack(pady=(0, 2))
        tk.Label(body2, text="AppImage", bg=ai_card_bg, fg=TEXT, font=F_CARD_TITLE).pack(pady=(0, 4))
        
        tk.Label(body2, text="Standalone AppImage in Applications folder", bg=ai_card_bg, fg=TEXT_MUTED, font=F_SMALL).pack(pady=(0, 15))
        
        status_text2 = "Installed ✓" if appimg else "Not installed"
        status_color2 = SUCCESS if appimg else TEXT_MUTED
        tk.Label(body2, text=status_text2, bg=ai_card_bg, fg=status_color2, font=F_BODY_B).pack(pady=(4, 0))
        
        ai_card.finalize()

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

    # -- PhotoGIMP + G'MIC + Batcher, one page -------------------------------
    # Toggling one of these no longer advances (advance=False): with three
    # decisions on the same page, jumping away after the first click would
    # make it impossible to pick more than one thing.

    def _wizard_render_components(self, parent):
        self._wizard_render_photogimp(parent)
        self._wizard_render_gmic(parent)
        self._wizard_render_batcher(parent)

    def _wizard_render_photogimp(self, parent):
        installed = photogimp_installed()

        def extra(body):
            if installed:
                RoundedButton(body, "Fix taskbar icon now", icon="refresh", variant="secondary", width=200,
                              command=self._repair_photogimp_desktop).pack(anchor="w", pady=(0, 8))

        self._wizard_toggle_card(
            parent, key="photogimp", title="PhotoGIMP", icon_kind="photogimp",
            installed=installed, description="Icons, shortcuts, splash screen, UI layout",
            install_label="Install PhotoGIMP",
            install_run=lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0]),
            uninstall_run=lambda job: remove_photogimp(job),
            extra=extra,
            advance=False,
            shortcut_num="1",
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
            parent, key="gmic", title="G'MIC", icon_kind="gmic",
            installed=installed, description="Extra filter collection for GIMP",
            install_label="Install G'MIC",
            install_run=lambda job: install_gmic_only(job),
            uninstall_run=lambda job: remove_gmic_only(job),
            install_enabled=available,
            disabled_reason=(None if available else
                              f"No G'MIC package on this distribution release — see {GMIC_DOWNLOAD_PAGE} "
                              "for a manual build."),
            advance=False,
            shortcut_num="2",
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
        setup_install_key = "sam_setup:install"

        model_widgets: list[tuple] = []       # (button, spec, installed)
        queue_all_buttons: list = []

        # -- PyTorch Build Selector Card (Compact and Clean) --
        card = RoundedCard(parent)
        card.pack(fill="x", pady=(0, 10))
        body = card.body
        
        row = tk.Frame(body, bg=CARD_BG)
        row.pack(fill="x", padx=4, pady=4)
        
        tk.Label(row, text="PyTorch build", bg=CARD_BG, fg=TEXT, font=F_BODY_B).pack(
            side="left", padx=(0, 12))
            
        combo = ctk.CTkComboBox(
            row, variable=self.torch_choice, values=list(TORCH_INDEX_URLS.keys()),
            state="readonly", width=340, height=36, corner_radius=10, font=F_BODY,
            fg_color=FIELD_BG, border_color=CARD_BORDER, border_width=1, text_color=TEXT,
            button_color=FIELD_BG, button_hover_color=SECONDARY_HOVER,
            dropdown_fg_color=FIELD_BG, dropdown_hover_color=SECONDARY_HOVER,
            dropdown_text_color=TEXT, dropdown_font=F_BODY)
        combo.pack(side="left")
        self._pytorch_combo = combo
        
        # Bind combobox clicks
        combo.bind("<Button-1>", lambda e: combo._clicked(), add="+")
        if hasattr(combo, "_entry"):
            combo._entry.bind("<Button-1>", lambda e: combo._clicked(), add="+")
            try:
                combo._entry.configure(cursor="hand2")
            except Exception:
                pass
        try:
            combo.configure(cursor="hand2")
        except Exception:
            pass
            
        card.finalize()

        # Helper to sync SAM setup in the plan
        def sync_sam_setup_in_plan():
            has_any_model_install = any(self.plan.has(f"sam_model:{spec.key}:install") for spec in MODEL_REGISTRY)
            if self.plan.has("sam3:install"):
                has_any_model_install = True
                
            if has_any_model_install:
                if not self.plan.has(setup_install_key):
                    self.plan.add(PlannedAction(setup_install_key, "Install SAM backend", "install", self._sam_setup_install_run()))
            else:
                self.plan.discard(setup_install_key)

        # -- models, by family --
        autowrap_label(
            parent,
            "Quality/Speed are rough 1-5 estimates, comparable within a family. Already-downloaded models "
            "are never a checkbox again — Remove just queues their deletion for the final install step.",
            fg=TEXT_MUTED, bg=BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(6, 10))

        rec_key = recommended_model_key(self.hw)

        if not hasattr(self, "_sam_expanded_family"):
            self._sam_expanded_family = "SAM1"

        def show_sam_category(fam_key):
            if self._sam_expanded_family != fam_key:
                self._sam_expanded_family = fam_key
                rebuild_sam_families()

        self.show_sam_category = show_sam_category

        self._sam_families_frame = tk.Frame(parent, bg=BG)
        self._sam_families_frame.pack(fill="x", expand=True)

        rec_key = recommended_model_key(self.hw)
        self._sam_model_widgets = []
        self._sam_family_cards = {}

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
            sync_sam_setup_in_plan()
            refresh_sam_page()

        def render_family_once(family_name, family_key):
            fam_card = RoundedCard(self._sam_families_frame)
            # Note: do NOT pack here — rebuild_sam_families controls packing order
            
            # Collapsible header
            head = tk.Frame(fam_card.body, bg=CARD_BG)
            head.pack(fill="x", pady=(0, 4))
            
            arrow_var = tk.StringVar(value="▶")
            arrow_lbl = tk.Label(head, textvariable=arrow_var, bg=CARD_BG, fg=TEXT, font=F_SECTION)
            arrow_lbl.pack(side="left", padx=(0, 6))
            
            title_lbl = tk.Label(head, text=family_name, bg=CARD_BG, fg=TEXT, font=F_SECTION)
            title_lbl.pack(side="left")
            
            queue_all_btn = RoundedButton(head, "Queue all missing", icon="install", variant="secondary",
                                           width=170)
            queue_all_btn.pack(side="right")
            queue_all_btn.command = lambda: queue_all(family_key)
            self._wizard_cards[f"queue_all_{family_key.lower()}"] = queue_all_btn.command
            
            # Container for models (not packed yet — rebuild_sam_families controls it)
            container = tk.Frame(fam_card.body, bg=CARD_BG)
                
            # Toggle logic
            arrow_lbl.bind("<Button-1>", lambda e: show_sam_category(family_key))
            title_lbl.bind("<Button-1>", lambda e: show_sam_category(family_key))
            head.bind("<Button-1>", lambda e: show_sam_category(family_key))
            for w in (arrow_lbl, title_lbl, head):
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass

            family_models = [m for m in MODEL_REGISTRY if m.family == family_key]
            for idx, spec in enumerate(family_models):
                installed = model_installed(spec)

                row = RoundedCard(container, bg=CARD_BG, border=CARD_BORDER,
                                  hover_bg="#2f323a", active_border=None,
                                  active_width=1, hover_border=ACCENT, pad=14, radius=16)
                row.pack(fill="x", pady=6)
                rbody = row.body
                top = tk.Frame(rbody, bg=CARD_BG)
                top.pack(fill="both", expand=True)
                
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

                right = tk.Frame(top, bg=CARD_BG)
                right.pack(side="right", padx=(16, 0), fill="y")
                
                tk.Label(right, text=f"[Shift {idx + 1}]", bg=CARD_BG, fg=TEXT_MUTED, font=F_SMALL_B).pack(
                    side="left", padx=(0, 10))
                
                rik, ric = ("check", SUCCESS) if installed else ("circle", CARD_BORDER)
                right_canvas = icon_canvas(right, rik, color=ric, size=28, bg=CARD_BG)
                right_canvas.pack(anchor="center", expand=True)
                
                def make_toggle_cmd(s=spec):
                    ikey, rkey = f"sam_model:{s.key}:install", f"sam_model:{s.key}:remove"
                    def cmd():
                        inst = model_installed(s)
                        if inst:
                            self.plan.toggle(PlannedAction(rkey, f"Remove {s.label}", "remove",
                                                            self._sam_model_remove_run(s)))
                        else:
                            self.plan.toggle(PlannedAction(ikey, f"Download {s.label}", "install",
                                                            self._sam_model_install_run(s)))
                        sync_sam_setup_in_plan()
                        refresh_sam_page()
                    return cmd
                
                row._command = make_toggle_cmd()
                self._wizard_cards[f"sam_model:{spec.key}"] = row._command
                self._sam_model_widgets.append((row, right_canvas, spec, installed))
                row.finalize()
            fam_card.finalize()
            return {
                "card_widget": fam_card,
                "arrow_var": arrow_var,
                "container": container,
            }

        # Build all family cards once (not yet packed)
        self._sam_family_cards["SAM1"] = render_family_once("SAM 1 (1)", "SAM1")
        self._sam_family_cards["SAM2"] = render_family_once("SAM 2 (2)", "SAM2")
        self._sam_family_cards["SAM3"] = self._wizard_render_sam3_dynamic(
            self._sam_families_frame, False,
            on_toggle=lambda: (sync_sam_setup_in_plan(), refresh_sam_page()),
            on_header_click=lambda: show_sam_category("SAM3"))

        def rebuild_sam_families():
            # 1. Unpack all family cards
            for key in ("SAM1", "SAM2", "SAM3"):
                if key in self._sam_family_cards:
                    self._sam_family_cards[key]["card_widget"].pack_forget()
            
            # 2. Compute ordering: active category first
            all_families = ["SAM1", "SAM2", "SAM3"]
            expanded_key = self._sam_expanded_family
            order = [expanded_key] + [k for k in all_families if k != expanded_key]
            
            # 3. Repack in new order and update arrow/container state
            for key in order:
                fam_info = self._sam_family_cards[key]
                fam_info["card_widget"].pack(fill="x", pady=(0, 10))
                is_exp = (key == expanded_key)
                fam_info["arrow_var"].set("▼" if is_exp else "▶")
                if is_exp:
                    fam_info["container"].pack(fill="x", pady=(4, 0))
                else:
                    fam_info["container"].pack_forget()
            
            refresh_sam_page()

        def refresh_sam_page():
            for card, rcanvas, spec, installed in self._sam_model_widgets:
                if spec.key == "sam3":
                    if hasattr(card, "_sam3_refresher"):
                        card._sam3_refresher(model_installed(spec))
                    continue
                ikey, rkey = f"sam_model:{spec.key}:install", f"sam_model:{spec.key}:remove"
                curr_installed = model_installed(spec)
                q = self.plan.has(rkey) if curr_installed else self.plan.has(ikey)
                
                if q:
                    card._bg = "#2e1b1d" if curr_installed else "#152e20"
                    card._hover_bg = "#3b2527" if curr_installed else "#1e3d2c"
                    card._active_border = DANGER if curr_installed else SUCCESS
                    card._active_width = 2
                    rik, ric = ("trash", DANGER) if curr_installed else ("check", SUCCESS)
                else:
                    card._bg = CARD_BG
                    card._hover_bg = "#2f323a"
                    card._active_border = None
                    card._active_width = 1
                    rik, ric = ("check", SUCCESS) if curr_installed else ("circle", CARD_BORDER)
                
                rcanvas.delete("all")
                from ..icons import blit_icon
                blit_icon(rcanvas, 14, 14, rik, color=ric, size=28)
                card._update_colors()

        self._refresh_sam_page_fn = refresh_sam_page
        rebuild_sam_families()

    # -- SAM 3.1 (gated on Hugging Face) -------------------------------------

    def _wizard_render_sam3_dynamic(self, parent, is_expanded, on_toggle, on_header_click):
        spec = MODEL_BY_KEY["sam3"]
        installed = model_installed(spec)
        card = RoundedCard(parent)
        # Note: do NOT pack here — rebuild_sam_families controls packing order
        body = card.body

        # Collapsible header
        head = tk.Frame(body, bg=CARD_BG)
        head.pack(fill="x", pady=(0, 4))
        
        arrow_var = tk.StringVar(value="▼" if is_expanded else "▶")
        arrow_lbl = tk.Label(head, textvariable=arrow_var, bg=CARD_BG, fg=TEXT, font=F_SECTION)
        arrow_lbl.pack(side="left", padx=(0, 6))
        
        title_lbl = tk.Label(head, text="SAM 3 (3)", bg=CARD_BG, fg=TEXT, font=F_SECTION)
        title_lbl.pack(side="left")
        
        container = tk.Frame(body, bg=CARD_BG)
        if is_expanded:
            container.pack(fill="x", pady=(4, 0))
            
        arrow_lbl.bind("<Button-1>", lambda e: on_header_click())
        title_lbl.bind("<Button-1>", lambda e: on_header_click())
        head.bind("<Button-1>", lambda e: on_header_click())
        for w in (arrow_lbl, title_lbl, head):
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        # Top row inside container (not body directly)
        top = tk.Frame(container, bg=CARD_BG)
        top.pack(fill="x")
        left = tk.Frame(top, bg=CARD_BG)
        left.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(left, bg=CARD_BG)
        name_row.pack(anchor="w")
        tk.Label(name_row, text=f"{spec.label} details", bg=CARD_BG, fg=TEXT, font=F_ITEM_TITLE).pack(
            side="left")
        tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=F_SMALL).pack(side="left")
        rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

        install_key, remove_key = "sam3:install", "sam3:remove"

        autowrap_label(
            container, f"Gated on Hugging Face ({SAM3_HF_REPO_ID}) — request access, wait for approval, then "
                  "paste a READ token below. The token is only checked against the repo once the plan "
                  "actually runs, so queuing it now is free.",
            fg=TEXT_MUTED, bg=CARD_BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(12, 14))

        row1 = tk.Frame(container, bg=CARD_BG)
        row1.pack(fill="x", pady=(0, 10))
        RoundedButton(row1, "Request access on Hugging Face", icon="link", variant="secondary", width=270,
                      command=lambda: webbrowser.open(SAM3_HF_PAGE)).pack(side="left")

        row2 = tk.Frame(container, bg=CARD_BG)
        row2.pack(fill="x")
        tk.Label(row2, text="HF token", bg=CARD_BG, fg=TEXT, font=F_BODY_B).pack(side="left")
        hf_entry = ctk.CTkEntry(row2, textvariable=self.hf_token_var, show="•", width=300, height=36,
                                corner_radius=10, fg_color=FIELD_BG, border_color=CARD_BORDER,
                                border_width=1, text_color=TEXT)
        hf_entry.pack(side="left", padx=12)
        self._hf_token_entry = hf_entry

        if installed:
            sam3_btn = RoundedButton(row2, "Remove", icon="trash", variant="danger", width=130)
            sam3_btn.pack(side="left")

            def toggle_sam3():
                self.plan.toggle(PlannedAction(remove_key, "Remove SAM 3", "remove",
                                                lambda job: remove_sam3(job)))
                on_toggle()

            self._wizard_cards["sam3"] = toggle_sam3
            sam3_btn.command = toggle_sam3

            def refresh(present: bool):
                q = self.plan.has(remove_key)
                sam3_btn.set_text("Remove" + (" ✓" if q else ""))
        else:
            sam3_btn = RoundedButton(
                row2, "Add to plan", icon="install", variant="success", width=140,
                on_blocked=lambda: show_snackbar(self, "Enter a Hugging Face token first", tone="warn"))
            sam3_btn.pack(side="left")

            def token_entered() -> bool:
                return bool(self.hf_token_var.get().strip())

            def toggle_sam3():
                self.plan.toggle(PlannedAction(install_key, "Download SAM 3", "install",
                                                lambda job: self._run_sam3_download(job)))
                on_toggle()

            self._wizard_cards["sam3"] = toggle_sam3
            sam3_btn.command = toggle_sam3

            def refresh(present: bool):
                queued = self.plan.has(install_key)
                sam3_btn.set_enabled(queued or token_entered())
                sam3_btn.set_text("Add to plan" + (" ✓" if queued else ""))

        def on_token_changed(*_args):
            if not installed and self.plan.has(install_key):
                self.plan.add(PlannedAction(install_key, "Download SAM 3", "install",
                                             lambda job: self._run_sam3_download(job)))
            refresh(True)

        trace_id = self.hf_token_var.trace_add("write", on_token_changed)

        def _drop_token_trace(_e=None, tid=trace_id):
            try:
                self.hf_token_var.trace_remove("write", tid)
            except (tk.TclError, ValueError):
                pass

        sam3_btn.bind("<Destroy>", _drop_token_trace)

        self._sam_model_widgets.append((card, None, spec, installed))
        card._sam3_refresher = refresh

        refresh(True)
        card.finalize()
        return {
            "card_widget": card,
            "arrow_var": arrow_var,
            "container": container,
        }

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
            parent, key="batcher", title="Batcher (Optional)", icon_kind="batcher",
            installed=installed, description="Batch image processing / export layers",
            install_label="Install Batcher",
            install_run=lambda job: install_batcher(job),
            uninstall_run=lambda job: remove_batcher(job),
            advance=False,
            shortcut_num="3",
        )

    # -- Review & install --------------------------------------------------

    def _wizard_render_review(self, parent):
        self._review_rows_discard_commands = []
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
            
            # Map item keys to their specific vector icons for the left side
            left_icon = "box"
            first_key = keys[0] if keys else ""
            if step_key == "gimp" or "gimp_install" in first_key:
                left_icon = "gimp"
            elif "photogimp" in first_key:
                left_icon = "photogimp"
            elif "gmic" in first_key:
                left_icon = "gmic"
            elif "batcher" in first_key:
                left_icon = "batcher"
            elif "sam" in first_key:
                left_icon = "bolt"
                
            icon_canvas(line, left_icon, color=ACCENT, size=24, bg=CARD_BG).pack(side="left", padx=(0, 12))
            
            lbl = tk.Label(line, text=label, bg=CARD_BG, fg=TEXT, font=F_BODY_B, anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            
            # Status icon just before the trash button
            status_icon = "check" if kind == "install" else "trash"
            status_color = SUCCESS if kind == "install" else DANGER
            icon_canvas(line, status_icon, color=status_color, size=20, bg=CARD_BG).pack(side="left", padx=10)
            
            def discard_cmd(keys=keys):
                self._wizard_discard_many(keys)
            self._review_rows_discard_commands.append(discard_cmd)
            
            trash_btn = RoundedButton(line, "", icon="trash", variant="danger", width=40,
                                       command=discard_cmd)
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
                      width=340, height=44, command=self._wizard_start_install).pack(anchor="center", pady=(24, 12))

    def _wizard_discard_many(self, keys: list[str]):
        for key in keys:
            self.plan.discard(key)
        self._refresh_wizard_body()

    def _wizard_start_install(self):
        self._current_wizard_frame = None
        self.show_install_progress(list(self.plan))
