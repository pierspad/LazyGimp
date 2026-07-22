"""The paginated setup wizard (GIMP > PhotoGIMP > G'MIC > SAM > Batcher >
Review). PySide6 port of ``gui/pages/wizard.py``. Every page only queues
PlannedActions into ``self.plan``; nothing here touches disk.

Behavior is preserved exactly; only the toolkit changed. See
``lazygimp/gui/README.md`` for the old (Tk) -> new (Qt) API table this
was built against.

Structural note: this stays a *mixin* (same convention as the sibling
landing.py/uninstall.py/progress.py ports), not a QWidget subclass, so a
future ``LazyGimpApp`` can compose it alongside those exactly like the Tk
``LazyGimpApp`` does. It assumes the composing host object provides:

* ``self.root`` — the top-level QWidget/QMainWindow (dialog parent).
* ``self.root_frame`` — a QWidget whose layout gets cleared and rebuilt
  by every screen's show_*(), same role as the Tk engine's root_frame.
* ``self.hw`` — whatever ``hardware.detect_hardware()`` returned.
* ``self.run_in_background(fn, on_done=None)`` — runs ``fn(job)`` on a
  worker thread and calls ``on_done()`` back on the GUI thread.
* ``self.show_landing()`` and ``self.show_install_progress(actions)``.

None of that plumbing is ported here — it's the separate app.py
integration task the brief calls out — but the contract is identical to
the other page mixins', so wiring it up later should be a drop-in.

Two structural simplifications versus the Tk original, both judgment
calls documented in full in the porting report:

1. The Tk version's landing<->wizard and step<->step transitions used a
   hand-rolled ``.place()``-based slide animation (``_animate_slide``,
   ``_animate_slide_full``, ``_show_landing_over``). That machinery is
   fundamentally tied to Tk's geometry manager and isn't ported —
   screen/step switching here is instant. The step-caching perf property
   it protected (never tearing down/rebuilding a step's widgets just to
   revisit it) *is* preserved, via QStackedWidget (see below).
2. Global keyboard shortcuts (Backspace=back, Enter=next, digit keys for
   picking a card, Alt+Left/Right, ...) lived in ``gui/app.py``'s
   ``_on_global_key``, not in ``gui/pages/wizard.py`` — app.py is out of
   scope for this page port (same boundary the landing/uninstall/
   progress ports drew). The hooks that handler used
   (``self.wizard_steps``, ``self.wizard_index``, ``self._wizard_cards``,
   ``self.show_sam_category``, ``self._wizard_scroller``,
   ``self._pytorch_combo``, ``self._hf_token_entry``,
   ``self._review_rows_discard_commands``) are all still populated here
   under the same names, so a future app.py port can wire the same
   handler back up without changing this file.

Step switching uses a QStackedWidget: each step's outer container is
built once (on first visit) and kept alive in the stack for the rest of
the wizard's lifetime — switching steps is just ``setCurrentWidget()``,
never a rebuild. Within that, two different content-refresh strategies
are preserved from the Tk original because they mattered for perf/UX
there and still do here:

* "gimp" and "review" pages are cheap and state-dependent enough that
  their content is fully torn down and rebuilt every time the step is
  (re)entered.
* "components" and "sam" pages build their widgets exactly once and are
  only ever updated in place afterwards (via the refresher-callback
  lists below) — never destroyed and rebuilt — so picking/unpicking
  things there never flickers.
"""

from __future__ import annotations

import os
import shutil
import webbrowser
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QVBoxLayout, QWidget,
)

from ...constants import GMIC_DOWNLOAD_PAGE
from ...distro import detect_distro
from ...gimp_detect import find_gimp_binary, find_gimp_command
from ...gimp_install import (
    appimage_present, gimp_native_installed, gmic_available_on_this_release, gmic_installed,
    install_gimp_appimage, install_gimp_package_manager, install_gmic_only, remove_gmic_only,
)
from ...hardware import recommended_model_key, recommended_torch_index
from ...job import Job
from ...models import MODEL_BY_KEY, MODEL_REGISTRY, ModelSpec, model_installed, model_path
from ...photogimp import (
    install_photogimp, photogimp_installed, remove_photogimp, repair_desktop_integration,
)
from ...plan import InstallPlan, PlannedAction, WizardStep
from ...plugins import (
    batcher_installed, install_batcher, install_segany_plugin, remove_batcher,
    remove_segany_plugin, segany_plugin_installed, write_segany_plugin_settings,
)
from ...sam3 import SAM3_HF_PAGE, SAM3_HF_REPO_ID, download_sam3, remove_sam3, sam3_failure_message
from ...sam_backend import (
    TORCH_INDEX_URLS, backend_ready, install_sam_backend, remove_sam_backend, write_sam_info,
)
from ..dialogs import show_snackbar, themed_confirm, themed_info
from ..icons import icon_label, render_icon_pixmap
from ..theme import (
    ACCENT, BG, CARD_BG, CARD_BORDER, DANGER, DISABLED_BG, DISABLED_TEXT, F_BODY, F_BODY_B,
    F_CARD_TITLE, F_H3, F_ITEM_TITLE, F_SECTION, F_SMALL, F_SMALL_B, FIELD_BG, SUCCESS, TEXT, TEXT_MUTED,
    WARNING, qfont,
)
from ..widgets import (
    RoundedButton, RoundedCard, ScrollableFrame, autowrap_label, bind_click_recursive, callout,
)


# ---------------------------------------------------------------------------
# Module-local helpers (kept duplicated rather than shared with the sibling
# page modules, so each stays self-contained while being developed/edited
# in parallel — same rationale landing.py/uninstall.py give for their own
# copy of _clear_root_frame).
# ---------------------------------------------------------------------------

def _ensure_vbox(widget: QWidget) -> QVBoxLayout:
    layout = widget.layout()
    if layout is None:
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
    return layout


def _clear_root_frame(root_frame: QWidget, keep=None) -> QVBoxLayout:
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


def _clear_layout(widget: QWidget) -> None:
    """Removes every child widget from `widget`'s own layout — the Qt
    counterpart of the Tk engine's ``for w in body_parent.winfo_children():
    w.destroy()`` sweep used before a full re-render of a step's body."""
    layout = widget.layout()
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


def _label(parent, text, font, color) -> QLabel:
    lbl = QLabel(text, parent)
    lbl.setFont(qfont(font))
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    return lbl


def _rating_widget(parent, quality: int, speed: int) -> QWidget:
    """Qt port of ``gui/helpers.py``'s rating_widget() — not part of the
    shared gui widget library (per gui/README.md, it wasn't in scope
    for the foundation phase), so it's kept local to whichever page needs
    it, same as the Tk engine's own gui/helpers.py placement."""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(2)

    def add_dots(score: int):
        for i in range(5):
            dot = QLabel(row)
            dot.setFixedSize(8, 8)
            color = ACCENT if i < score else CARD_BORDER
            dot.setStyleSheet(f"background-color: {color}; border-radius: 4px; border: none;")
            layout.addWidget(dot)

    layout.addWidget(_label(row, "Quality", F_SMALL, TEXT_MUTED))
    layout.addSpacing(2)
    add_dots(quality)
    layout.addSpacing(14)
    layout.addWidget(_label(row, "Speed", F_SMALL, TEXT_MUTED))
    layout.addSpacing(2)
    add_dots(speed)
    layout.addStretch(1)
    return row


class _StringVar:
    """Minimal get()/set() box standing in for a tk.StringVar, for the two
    bits of wizard state (PyTorch build choice, HF token) that used to be
    tk.StringVars. Not part of gui/widgets.py (widgets.py only has
    BoolVar, for ModernCheckbox) since this is page-local state, not a
    widget concern. Plain-attribute reads/writes on a CPython object are
    effectively atomic, so this stays safe to read from the background
    job thread the same way the Tk StringVar was."""

    def __init__(self, value: str = ""):
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


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

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def show_wizard(self):
        self.plan = InstallPlan()

        # Preselect defaults on startup.
        if not (gimp_native_installed() or appimage_present() or find_gimp_binary()):
            if detect_distro():
                self.plan.add(PlannedAction(
                    "gimp_install_pm", "Install GIMP (package manager)", "install",
                    lambda job: install_gimp_package_manager(job, include_gmic=False)))

        if not photogimp_installed():
            self.plan.add(PlannedAction(
                "photogimp:install", "Install PhotoGIMP", "install",
                lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0])))

        if gmic_available_on_this_release() and not gmic_installed():
            self.plan.add(PlannedAction("gmic:install", "Install G'MIC", "install",
                                         lambda job: install_gmic_only(job)))

        if not batcher_installed():
            self.plan.add(PlannedAction("batcher:install", "Install Batcher", "install",
                                         lambda job: install_batcher(job)))

        spec = MODEL_BY_KEY["sam2_hiera_small"]
        if not model_installed(spec):
            self.plan.add(PlannedAction(
                f"sam_model:{spec.key}:install", f"Download {spec.label}", "install",
                self._sam_model_install_run(spec)))
            if not backend_ready() or not segany_plugin_installed():
                self.plan.add(PlannedAction("sam_setup:install", "Install SAM backend", "install",
                                             self._sam_setup_install_run()))

        default_choice = list(TORCH_INDEX_URLS.keys())[
            list(TORCH_INDEX_URLS.values()).index(recommended_torch_index(self.hw))]
        self.torch_choice = _StringVar(default_choice)
        self.hf_token_var = _StringVar("")

        self.wizard_steps: list[WizardStep] = self._build_wizard_steps()
        self.wizard_index = 0

        self._wizard_cards = {}
        self._review_rows_discard_commands = []
        self._component_card_refreshers = []
        self._sam_model_widgets = []
        self._sam_family_cards = {}
        self._sam_expanded_family = None
        self._sam_families_frame = None
        self._pytorch_combo = None
        self._hf_token_entry = None
        self._wizard_scroller = None
        self._refresh_sam_page_fn = None

        # step.key -> outer QWidget added to the QStackedWidget (built once,
        # kept alive for the rest of this wizard session — the Qt
        # counterpart of the Tk engine's `_wizard_page_cache`).
        self._wizard_page_cache: dict[str, QWidget] = {}
        self._wizard_body_parent_by_step: dict[str, QWidget] = {}
        self._wizard_page_built: set[str] = set()
        self._wizard_next_btn = None
        self._current_wizard_frame = None

        self._render_wizard_shell()
        self._render_wizard_step()

    def _build_wizard_steps(self) -> list[WizardStep]:
        steps = []
        if not (gimp_native_installed() or appimage_present() or find_gimp_binary()):
            steps.append(WizardStep("gimp", "GIMP (prerequisite)", prerequisite=True))
        steps.append(WizardStep("components", "Select which plugin you want to add"))
        steps.append(WizardStep("sam", "SAM (segmentation models)"))
        steps.append(WizardStep("review", "Review & install"))
        return steps

    # ------------------------------------------------------------------
    # Shell (header + step stack + nav bar)
    # ------------------------------------------------------------------

    def _render_wizard_shell(self):
        self.current_screen = "wizard"
        root_layout = _clear_root_frame(self.root_frame)

        outer = QWidget(self.root_frame)
        self._current_wizard_frame = outer
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 16, 0, 16)
        outer_layout.setSpacing(10)
        root_layout.addWidget(outer, 1)

        header = QWidget(outer)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(26, 0, 26, 0)
        self._wizard_title_label = _label(header, "", F_H3, TEXT)
        header_layout.addWidget(self._wizard_title_label)
        header_layout.addStretch(1)
        self._wizard_step_label = _label(header, "", F_BODY, TEXT_MUTED)
        header_layout.addWidget(self._wizard_step_label)
        outer_layout.addWidget(header)

        self._wizard_stack = QStackedWidget(outer)
        outer_layout.addWidget(self._wizard_stack, 1)

        self._wizard_nav_frame = QWidget(outer)
        self._wizard_nav_layout = QHBoxLayout(self._wizard_nav_frame)
        self._wizard_nav_layout.setContentsMargins(26, 0, 26, 0)
        outer_layout.addWidget(self._wizard_nav_frame)

    def _rebuild_nav_buttons(self, step: WizardStep):
        _clear_layout(self._wizard_nav_frame)
        back_btn = RoundedButton(self._wizard_nav_frame, "← Back [Backspace]", variant="secondary",
                                  width=160, command=self._wizard_back)
        self._wizard_nav_layout.addWidget(back_btn)
        self._wizard_nav_layout.addStretch(1)

        self._wizard_next_btn = None
        if step.key != "review":
            if not step.prerequisite:
                skip_btn = RoundedButton(self._wizard_nav_frame, "Skip →", variant="secondary",
                                          width=110, command=self._wizard_advance)
                self._wizard_nav_layout.addWidget(skip_btn)
            next_btn = RoundedButton(self._wizard_nav_frame, "Next [Enter] →", variant="primary",
                                      width=160, command=self._wizard_advance)
            self._wizard_nav_layout.addWidget(next_btn)
            next_btn.set_enabled(self._wizard_can_advance())
            self._wizard_next_btn = next_btn

    def _get_or_create_step_page(self, step: WizardStep) -> QWidget:
        if step.key in self._wizard_page_cache:
            return self._wizard_page_cache[step.key]

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 6, 0, 0)
        if step.key in ("sam", "review"):
            scroller = ScrollableFrame(page)
            outer.addWidget(scroller)
            body_parent = scroller.inner
            body_layout = QVBoxLayout(body_parent)
            body_layout.setContentsMargins(26, 0, 6, 0)
            if step.key == "sam":
                self._wizard_scroller = scroller
        else:
            body_parent = QWidget(page)
            body_layout = QVBoxLayout(body_parent)
            body_layout.setContentsMargins(26, 0, 26, 0)
            outer.addWidget(body_parent)

        self._wizard_page_cache[step.key] = page
        self._wizard_body_parent_by_step[step.key] = body_parent
        self._wizard_stack.addWidget(page)
        return page

    def _render_wizard_step(self):
        self.current_screen = "wizard"
        step = self.wizard_steps[self.wizard_index]
        self._wizard_title_label.setText(step.title)
        self._wizard_step_label.setText(f"Step {self.wizard_index + 1} of {len(self.wizard_steps)}")
        self._rebuild_nav_buttons(step)

        page = self._get_or_create_step_page(step)
        body_parent = self._wizard_body_parent_by_step[step.key]

        if step.key == "gimp":
            _clear_layout(body_parent)
            self._wizard_render_gimp(body_parent)
        elif step.key == "review":
            _clear_layout(body_parent)
            self._wizard_render_review(body_parent)
        elif step.key == "components":
            if step.key not in self._wizard_page_built:
                self._wizard_page_built.add(step.key)
                self._wizard_render_components(body_parent)
            else:
                for fn in self._component_card_refreshers:
                    try:
                        fn()
                    except Exception:
                        pass
        elif step.key == "sam":
            if step.key not in self._wizard_page_built:
                self._wizard_page_built.add(step.key)
                self._wizard_render_sam(body_parent)
            elif self._refresh_sam_page_fn:
                self._refresh_sam_page_fn()

        self._wizard_stack.setCurrentWidget(page)
        if self._wizard_next_btn is not None:
            self._wizard_next_btn.set_enabled(self._wizard_can_advance())

    def _refresh_wizard_body(self):
        """Re-render only the current page's content, in place — the Qt
        counterpart of the Tk engine's method of the same name, used by
        the review page's per-row discard action."""
        step = self.wizard_steps[self.wizard_index]
        body_parent = self._wizard_body_parent_by_step.get(step.key)
        if body_parent is None:
            return
        _clear_layout(body_parent)
        getattr(self, self._WIZARD_RENDERERS[step.key])(body_parent)
        if self._wizard_next_btn is not None:
            self._wizard_next_btn.set_enabled(self._wizard_can_advance())

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

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
            self._current_wizard_frame = None
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

    def _wizard_discard_many(self, keys: list[str]):
        for key in keys:
            self.plan.discard(key)
        self._refresh_wizard_body()

    def _wizard_start_install(self):
        self._current_wizard_frame = None
        self.show_install_progress(list(self.plan))

    # ------------------------------------------------------------------
    # Generic install/remove toggle card (PhotoGIMP / G'MIC / Batcher)
    # ------------------------------------------------------------------

    def _wizard_toggle_card(self, parent, *, key: str, title: str, icon_kind: str, installed: bool,
                             description: str, install_label: str, install_run, uninstall_run,
                             uninstall_label: str = "Uninstall", install_enabled: bool = True,
                             disabled_reason: Optional[str] = None, advance: bool = True, extra=None,
                             shortcut_num: Optional[str] = None):
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

        if is_card_enabled:
            if queued:
                card_bg = "#2e1b1d" if installed else "#152e20"
                card_hover_bg = "#3b2527" if installed else "#1e3d2c"
                active_border = DANGER if installed else SUCCESS
                active_width = 2
            else:
                if installed:
                    card_bg = "#132838"
                    card_hover_bg = "#1a344a"
                    active_border = "#38bdf8"
                    active_width = 1.5
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

        if installed:
            if queued:
                status_text, status_color, right_icon_kind, right_icon_color = (
                    "queued for removal", DANGER, "trash", DANGER)
            else:
                status_text, status_color, right_icon_kind, right_icon_color = (
                    "installed", "#38bdf8", "check", "#38bdf8")
        else:
            if queued:
                status_text, status_color, right_icon_kind, right_icon_color = (
                    "queued for install", SUCCESS, "check", SUCCESS)
            else:
                status_text, status_color, right_icon_kind, right_icon_color = (
                    "not installed", TEXT_MUTED, "circle", CARD_BORDER)

        def on_card_click():
            if not is_card_enabled:
                show_snackbar(self, disabled_reason or "Not available", "warn")
                return
            now_queued = self.plan.toggle(PlannedAction(action_key, action_label, action_kind, action_run))
            if advance and now_queued:
                self._wizard_advance()
            else:
                if self._wizard_next_btn is not None:
                    self._wizard_next_btn.set_enabled(self._wizard_can_advance())
                update_card_ui()

        self._wizard_cards[key] = on_card_click

        def update_card_ui():
            q = self.plan.has(action_key)
            if q:
                card._bg = "#2e1b1d" if installed else "#152e20"
                card._hover_bg = "#3b2527" if installed else "#1e3d2c"
                card._active_border = DANGER if installed else SUCCESS
                card._active_width = 2
                if installed:
                    ds, sc, rik, ric = "queued for removal", DANGER, "trash", DANGER
                else:
                    ds, sc, rik, ric = "queued for install", SUCCESS, "check", SUCCESS
            else:
                if installed:
                    card._bg = "#132838"
                    card._hover_bg = "#1a344a"
                    card._active_border = "#38bdf8"
                    card._active_width = 1.5
                    ds, sc, rik, ric = "installed", "#38bdf8", "check", "#38bdf8"
                else:
                    card._bg = CARD_BG
                    card._hover_bg = "#2f323a"
                    card._active_border = None
                    card._active_width = 1
                    ds, sc, rik, ric = "not installed", TEXT_MUTED, "circle", CARD_BORDER
            status_label.setText(ds)
            status_label.setStyleSheet(f"color: {sc}; background: transparent;")
            right_icon_label.setPixmap(render_icon_pixmap(rik, ric, 28))
            card._update_style()

        self._component_card_refreshers.append(update_card_ui)

        if is_card_enabled:
            card = RoundedCard(parent, bg=card_bg, border=CARD_BORDER, command=on_card_click,
                                hover_bg=card_hover_bg, active_border=active_border,
                                active_width=active_width, hover_border=ACCENT, pad=12, radius=14)
        else:
            card = RoundedCard(parent, bg=card_bg, border=CARD_BORDER, pad=12, radius=14)
        parent.layout().addWidget(card)

        body_layout = QVBoxLayout(card.body)
        body_layout.setContentsMargins(4, 4, 4, 4)

        main_row = QWidget(card.body)
        main_row_layout = QHBoxLayout(main_row)
        main_row_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(main_row)

        left_frame = QWidget(main_row)
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(0, 0, 16, 0)
        plugin_icon_color = ACCENT if is_card_enabled else DISABLED_TEXT
        p_icon = icon_label(left_frame, icon_kind, color=plugin_icon_color, size=36)
        left_layout.addWidget(p_icon, alignment=Qt.AlignCenter)
        main_row_layout.addWidget(left_frame)

        mid_frame = QWidget(main_row)
        mid_layout = QVBoxLayout(mid_frame)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        title_label = _label(mid_frame, title, F_CARD_TITLE, TEXT)
        mid_layout.addWidget(title_label)
        desc_label = autowrap_label(mid_frame, description, fg=TEXT_MUTED, bg=card_bg, font=F_SMALL)
        mid_layout.addWidget(desc_label)
        status_label = _label(mid_frame, status_text, F_BODY_B, status_color)
        mid_layout.addWidget(status_label)
        main_row_layout.addWidget(mid_frame, 1)

        right_frame = QWidget(main_row)
        right_layout = QHBoxLayout(right_frame)
        right_layout.setContentsMargins(16, 0, 0, 0)
        if shortcut_num:
            right_layout.addWidget(_label(right_frame, f"({shortcut_num})", F_SMALL_B, TEXT_MUTED))
        right_icon_label = icon_label(right_frame, right_icon_kind, color=right_icon_color, size=28)
        right_layout.addWidget(right_icon_label)
        main_row_layout.addWidget(right_frame)

        if extra:
            extra_frame = QWidget(card.body)
            extra_layout = QVBoxLayout(extra_frame)
            extra_layout.setContentsMargins(52, 6, 0, 0)
            body_layout.addWidget(extra_frame)
            extra(extra_frame)

        if not is_card_enabled and disabled_reason:
            callout_frame = QWidget(card.body)
            cf_layout = QVBoxLayout(callout_frame)
            cf_layout.setContentsMargins(52, 6, 0, 0)
            body_layout.addWidget(callout_frame)
            callout(callout_frame, disabled_reason, "warn")

        card.finalize()

    # ------------------------------------------------------------------
    # GIMP (prerequisite; mandatory, exclusive choice of method)
    # ------------------------------------------------------------------

    def _wizard_render_gimp(self, parent):
        layout = parent.layout()
        native = gimp_native_installed()
        appimg = appimage_present()
        distro = detect_distro()

        pm_selected = self.plan.has("gimp_install_pm")
        ai_selected = self.plan.has("gimp_install_appimage")

        # Tk centered the two cards at relx=0.5, rely=0.45 inside a frame
        # that filled the whole page. Qt has no direct equivalent inside a
        # real QLayout; a 1:2 stretch split above/below the row approximates
        # the same just-above-center position while staying a resizable
        # layout (same approach landing.py's show_landing() uses).
        layout.addStretch(1)
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(18)
        row_layout.addStretch(1)

        # -- Card 1: Package Manager --
        pm_card_bg = "#152e20" if pm_selected else (CARD_BG if distro else DISABLED_BG)
        pm_card_hover_bg = "#1e3d2c" if pm_selected else ("#2f323a" if distro else DISABLED_BG)
        pm_card_border = CARD_BORDER if distro else DISABLED_BG
        pm_command = (lambda: self._wizard_pick_gimp_method("pm")) if distro else None

        pm_card = RoundedCard(
            row, bg=pm_card_bg, border=pm_card_border, command=pm_command,
            hover_bg=pm_card_hover_bg, active_border=SUCCESS if pm_selected else None,
            active_width=2 if pm_selected else 1, hover_border=ACCENT if distro else None,
            width=360, height=280)
        body1 = QVBoxLayout(pm_card.body)
        body1.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        distro_icon = distro if distro else "linux"
        icon_color = SUCCESS if (native or pm_selected) else TEXT_MUTED
        body1.addSpacing(20)
        body1.addWidget(icon_label(pm_card.body, distro_icon, color=icon_color, size=64),
                         alignment=Qt.AlignHCenter)
        body1.addSpacing(10)
        body1.addWidget(_label(pm_card.body, "(1)", F_BODY_B, TEXT_MUTED), alignment=Qt.AlignHCenter)
        body1.addWidget(_label(pm_card.body, "Package Manager", F_CARD_TITLE, TEXT),
                         alignment=Qt.AlignHCenter)
        distro_name = distro.capitalize() if distro else "Linux"
        body1.addWidget(
            _label(pm_card.body, f"Use system package manager ({distro_name})", F_SMALL, TEXT_MUTED),
            alignment=Qt.AlignHCenter)
        body1.addSpacing(15)

        status_text1 = "Installed ✓" if native else "Not installed"
        status_color1 = SUCCESS if native else TEXT_MUTED
        body1.addWidget(_label(pm_card.body, status_text1, F_BODY_B, status_color1),
                         alignment=Qt.AlignHCenter)

        if not distro:
            body1.addSpacing(6)
            body1.addWidget(autowrap_label(pm_card.body, "No supported distro detected", fg=WARNING,
                                            bg=pm_card_bg, font=F_SMALL, justify=Qt.AlignHCenter))

        pm_card.finalize()
        row_layout.addWidget(pm_card)

        # -- Card 2: AppImage --
        ai_card_bg = "#152e20" if ai_selected else CARD_BG
        ai_card_hover_bg = "#1e3d2c" if ai_selected else "#2f323a"
        ai_card = RoundedCard(
            row, bg=ai_card_bg, border=CARD_BORDER,
            command=lambda: self._wizard_pick_gimp_method("appimage"),
            hover_bg=ai_card_hover_bg, active_border=SUCCESS if ai_selected else None,
            active_width=2 if ai_selected else 1, hover_border=ACCENT, width=360, height=280)
        body2 = QVBoxLayout(ai_card.body)
        body2.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        icon_color2 = SUCCESS if (appimg or ai_selected) else TEXT_MUTED
        body2.addSpacing(20)
        body2.addWidget(icon_label(ai_card.body, "box", color=icon_color2, size=64),
                         alignment=Qt.AlignHCenter)
        body2.addSpacing(10)
        body2.addWidget(_label(ai_card.body, "(2)", F_BODY_B, TEXT_MUTED), alignment=Qt.AlignHCenter)
        body2.addWidget(_label(ai_card.body, "AppImage", F_CARD_TITLE, TEXT), alignment=Qt.AlignHCenter)
        body2.addWidget(
            _label(ai_card.body, "Standalone AppImage in Applications folder", F_SMALL, TEXT_MUTED),
            alignment=Qt.AlignHCenter)
        body2.addSpacing(15)

        status_text2 = "Installed ✓" if appimg else "Not installed"
        status_color2 = SUCCESS if appimg else TEXT_MUTED
        body2.addWidget(_label(ai_card.body, status_text2, F_BODY_B, status_color2),
                         alignment=Qt.AlignHCenter)

        ai_card.finalize()
        row_layout.addWidget(ai_card)

        row_layout.addStretch(1)
        layout.addWidget(row)
        layout.addStretch(2)

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

    # ------------------------------------------------------------------
    # PhotoGIMP + G'MIC + Batcher, one page
    # ------------------------------------------------------------------

    def _wizard_render_components(self, parent):
        self._wizard_render_photogimp(parent)
        self._wizard_render_gmic(parent)
        self._wizard_render_batcher(parent)
        parent.layout().addStretch(1)

    def _wizard_render_photogimp(self, parent):
        installed = photogimp_installed()

        def extra(frame):
            if installed:
                btn = RoundedButton(frame, "Fix taskbar icon now", icon="refresh", variant="secondary",
                                     width=200, command=self._repair_photogimp_desktop)
                frame.layout().addWidget(btn)

        self._wizard_toggle_card(
            parent, key="photogimp", title="PhotoGIMP", icon_kind="photogimp",
            installed=installed, description="Icons, shortcuts, splash screen, UI layout",
            install_label="Install PhotoGIMP",
            install_run=lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0]),
            uninstall_run=lambda job: remove_photogimp(job),
            extra=extra, advance=False, shortcut_num="1")

    def _repair_photogimp_desktop(self):
        def task(job: Job):
            repair_desktop_integration(job)

        def done():
            if self.current_screen == "wizard":
                self._refresh_wizard_body()
            show_snackbar(self, "Desktop entry fixed — restart GIMP and re-pin it", tone="ok")

        self.run_in_background(task, on_done=done)

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
            advance=False, shortcut_num="2")

    def _wizard_render_batcher(self, parent):
        installed = batcher_installed()
        self._wizard_toggle_card(
            parent, key="batcher", title="Batcher (Optional)", icon_kind="batcher",
            installed=installed, description="Batch image processing / export layers",
            install_label="Install Batcher",
            install_run=lambda job: install_batcher(job),
            uninstall_run=lambda job: remove_batcher(job),
            advance=False, shortcut_num="3")

    # ------------------------------------------------------------------
    # SAM: PyTorch build selector + model families + SAM 3.1
    # ------------------------------------------------------------------

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

    def _run_sam3_download(self, job: Job):
        token = self.hf_token_var.get().strip()
        if not token:
            job.log("No Hugging Face token was entered — skipping SAM 3.1.")
            return
        ok, tag = download_sam3(job, token)
        if not ok:
            job.log(sam3_failure_message(tag))

    def _sync_sam_setup_in_plan(self):
        setup_install_key = "sam_setup:install"
        has_any_model_install = any(self.plan.has(f"sam_model:{spec.key}:install") for spec in MODEL_REGISTRY)
        if self.plan.has("sam3:install"):
            has_any_model_install = True
        if has_any_model_install:
            if not self.plan.has(setup_install_key):
                self.plan.add(PlannedAction(setup_install_key, "Install SAM backend", "install",
                                             self._sam_setup_install_run()))
        else:
            self.plan.discard(setup_install_key)

    def _show_sam_category(self, fam_key: str):
        if self._sam_expanded_family != fam_key:
            self._sam_expanded_family = fam_key
            self._rebuild_sam_families()

    def _sam_queue_all(self, family: str):
        missing = [m for m in MODEL_REGISTRY if m.family == family and not model_installed(m)]
        if not missing:
            themed_info(self.root, "Nothing to do", f"All {family} models are already installed.")
            return
        for spec in missing:
            key = f"sam_model:{spec.key}:install"
            if not self.plan.has(key):
                self.plan.add(PlannedAction(key, f"Download {spec.label}", "install",
                                             self._sam_model_install_run(spec)))
        self._sync_sam_setup_in_plan()
        self.refresh_sam_page()

    def _wizard_render_sam(self, parent):
        layout = parent.layout()

        # -- PyTorch build selector card --
        card = RoundedCard(parent)
        layout.addWidget(card)
        card_layout = QVBoxLayout(card.body)
        row = QWidget(card.body)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(_label(row, "PyTorch build", F_BODY_B, TEXT))
        combo = QComboBox(row)
        combo.addItems(list(TORCH_INDEX_URLS.keys()))
        combo.setCurrentText(self.torch_choice.get())
        combo.setFixedWidth(360)
        combo.setFixedHeight(38)
        combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {FIELD_BG};
                color: {TEXT};
                border: 1.5px solid {CARD_BORDER};
                border-radius: 8px;
                padding: 6px 36px 6px 12px;
                font-weight: bold;
            }}
            QComboBox:hover {{
                border: 1.5px solid {ACCENT};
                background-color: #363942;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 32px;
                border-left: 1.5px solid {CARD_BORDER};
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
                background: #25272e;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {ACCENT};
                width: 0;
                height: 0;
            }}
        """)
        combo.currentTextChanged.connect(self.torch_choice.set)
        row_layout.addWidget(combo)
        row_layout.addStretch(1)
        card_layout.addWidget(row)
        self._pytorch_combo = combo
        card.finalize()

        layout.addWidget(autowrap_label(
            parent,
            "Quality/Speed are rough 1-5 estimates, comparable within a family. Already-downloaded models "
            "are never a checkbox again — Remove just queues their deletion for the final install step.",
            fg=TEXT_MUTED, bg=BG, font=F_SMALL))

        rec_key = recommended_model_key(self.hw)
        if self._sam_expanded_family is None:
            self._sam_expanded_family = MODEL_BY_KEY[rec_key].family if rec_key in MODEL_BY_KEY else "SAM1"

        # Kept under the same attribute name as the Tk original — app.py's
        # (not-yet-ported) global key handler looked it up as
        # self.show_sam_category for the 1/2/3 SAM-family shortcuts.
        self.show_sam_category = self._show_sam_category

        self._sam_families_frame = QWidget(parent)
        fam_layout = QVBoxLayout(self._sam_families_frame)
        fam_layout.setContentsMargins(0, 0, 0, 0)
        fam_layout.setSpacing(10)
        layout.addWidget(self._sam_families_frame)

        self._sam_model_widgets = []
        self._sam_family_cards = {}
        self._sam_family_cards["SAM1"] = self._render_family_once("SAM 1 (1)", "SAM1", rec_key)
        self._sam_family_cards["SAM2"] = self._render_family_once("SAM 2 (2)", "SAM2", rec_key)
        self._sam_family_cards["SAM3"] = self._wizard_render_sam3_dynamic()

        self._refresh_sam_page_fn = self.refresh_sam_page
        self._rebuild_sam_families()

    def _rebuild_sam_families(self):
        layout = self._sam_families_frame.layout()
        order = [self._sam_expanded_family] + [k for k in ("SAM1", "SAM2", "SAM3")
                                                 if k != self._sam_expanded_family]
        for key in order:
            fam = self._sam_family_cards[key]
            layout.removeWidget(fam["card_widget"])
            layout.addWidget(fam["card_widget"])
            is_exp = key == self._sam_expanded_family
            fam["arrow_label"].setText("▼" if is_exp else "▶")
            fam["container"].setVisible(is_exp)
            fam["update_badges"](is_exp)
        self.refresh_sam_page()

    def _render_family_once(self, family_name: str, family_key: str, rec_key: str) -> dict:
        fam_card = RoundedCard(self._sam_families_frame)
        body_layout = QVBoxLayout(fam_card.body)

        head = QWidget(fam_card.body)
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 4)
        arrow_label = _label(head, "▶", F_SECTION, TEXT)
        head_layout.addWidget(arrow_label)
        head_layout.addWidget(_label(head, family_name, F_SECTION, TEXT))

        badge_frame = QWidget(head)
        badge_layout = QHBoxLayout(badge_frame)
        badge_layout.setContentsMargins(10, 0, 0, 0)
        badge_layout.setSpacing(4)
        head_layout.addWidget(badge_frame)

        family_models_list = [m for m in MODEL_REGISTRY if m.family == family_key]
        family_has_rec = any(m.key == rec_key for m in family_models_list)
        rec_badge_lbl = None
        if family_has_rec:
            rec_badge_lbl = _label(badge_frame, "★ Recommended", F_SMALL_B, ACCENT)
            badge_layout.addWidget(rec_badge_lbl)

        dot_labels = []
        for _ in family_models_list:
            dot = _label(badge_frame, "●", F_SMALL_B, CARD_BORDER)
            badge_layout.addWidget(dot)
            dot_labels.append(dot)

        def update_header_badges(is_expanded: bool):
            if rec_badge_lbl is not None:
                rec_badge_lbl.setStyleSheet(
                    f"color: {CARD_BG if is_expanded else ACCENT}; background: transparent;")
            for dot, spec in zip(dot_labels, family_models_list):
                if is_expanded:
                    dot.setStyleSheet(f"color: {CARD_BG}; background: transparent;")
                    continue
                inst = model_installed(spec)
                ikey, rkey2 = f"sam_model:{spec.key}:install", f"sam_model:{spec.key}:remove"
                queued_install = self.plan.has(ikey)
                queued_remove = self.plan.has(rkey2)
                if inst and not queued_remove:
                    colour = SUCCESS
                elif queued_install:
                    colour = ACCENT
                else:
                    colour = CARD_BORDER
                dot.setStyleSheet(f"color: {colour}; background: transparent;")

        head_layout.addStretch(1)
        queue_all_btn = RoundedButton(head, "Queue all missing", icon="install", variant="secondary",
                                       width=170, command=lambda: self._sam_queue_all(family_key))
        self._wizard_cards[f"queue_all_{family_key.lower()}"] = queue_all_btn.command
        head_layout.addWidget(queue_all_btn)
        body_layout.addWidget(head)

        container = QWidget(fam_card.body)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 4, 0, 0)
        container_layout.setSpacing(6)
        body_layout.addWidget(container)

        bind_click_recursive(head, lambda fk=family_key: self._show_sam_category(fk))

        for idx, spec in enumerate(family_models_list):
            installed = model_installed(spec)

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
                    self._sync_sam_setup_in_plan()
                    self.refresh_sam_page()
                return cmd

            toggle_cmd = make_toggle_cmd()
            row = RoundedCard(container, bg=CARD_BG, border=CARD_BORDER, command=toggle_cmd,
                               hover_bg="#2f323a", active_border=None, active_width=1,
                               hover_border=ACCENT, pad=14, radius=16)
            container_layout.addWidget(row)
            self._wizard_cards[f"sam_model:{spec.key}"] = toggle_cmd

            rbody_layout = QVBoxLayout(row.body)
            top = QWidget(row.body)
            top_layout = QHBoxLayout(top)
            top_layout.setContentsMargins(0, 0, 0, 0)
            rbody_layout.addWidget(top)

            left = QWidget(top)
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            name_row = QWidget(left)
            name_row_layout = QHBoxLayout(name_row)
            name_row_layout.setContentsMargins(0, 0, 0, 0)
            name_row_layout.addWidget(_label(name_row, spec.label, F_ITEM_TITLE, TEXT))
            name_row_layout.addWidget(_label(name_row, f"   {spec.size}", F_SMALL, TEXT_MUTED))
            if spec.key == rec_key:
                name_row_layout.addWidget(_label(name_row, "  ★ Recommended", F_SMALL_B, ACCENT))
            name_row_layout.addStretch(1)
            left_layout.addWidget(name_row)
            left_layout.addWidget(_rating_widget(left, spec.quality, spec.speed))
            top_layout.addWidget(left, 1)

            right = QWidget(top)
            right_layout = QHBoxLayout(right)
            right_layout.setContentsMargins(16, 0, 0, 0)
            right_layout.addWidget(_label(right, f"[Shift {idx + 1}]", F_SMALL_B, TEXT_MUTED))
            rik, ric = ("check", SUCCESS) if installed else ("circle", CARD_BORDER)
            right_icon_label = icon_label(right, rik, color=ric, size=28)
            right_layout.addWidget(right_icon_label)
            top_layout.addWidget(right)

            self._sam_model_widgets.append((row, right_icon_label, spec, installed))
            row.finalize()

        fam_card.finalize()
        return {
            "card_widget": fam_card,
            "arrow_label": arrow_label,
            "container": container,
            "update_badges": update_header_badges,
        }

    # -- SAM 3.1 (gated on Hugging Face) ---------------------------------

    def _wizard_render_sam3_dynamic(self) -> dict:
        spec = MODEL_BY_KEY["sam3"]
        installed = model_installed(spec)
        card = RoundedCard(self._sam_families_frame)
        body_layout = QVBoxLayout(card.body)

        head = QWidget(card.body)
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 4)
        arrow_label = _label(head, "▶", F_SECTION, TEXT)
        head_layout.addWidget(arrow_label)
        head_layout.addWidget(_label(head, "SAM 3 (3)", F_SECTION, TEXT))

        sam3_dot = _label(head, "●", F_SMALL_B, CARD_BORDER)
        head_layout.addSpacing(10)
        head_layout.addWidget(sam3_dot)
        head_layout.addStretch(1)
        body_layout.addWidget(head)

        install_key, remove_key = "sam3:install", "sam3:remove"

        def update_sam3_badges(is_exp: bool):
            if is_exp:
                sam3_dot.setStyleSheet(f"color: {CARD_BG}; background: transparent;")
                return
            if installed and not self.plan.has(remove_key):
                sam3_dot.setStyleSheet(f"color: {SUCCESS}; background: transparent;")
            elif self.plan.has(install_key):
                sam3_dot.setStyleSheet(f"color: {ACCENT}; background: transparent;")
            else:
                sam3_dot.setStyleSheet(f"color: {CARD_BORDER}; background: transparent;")

        container = QWidget(card.body)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.addWidget(container)

        bind_click_recursive(head, lambda: self._show_sam_category("SAM3"))

        top = QWidget(container)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        left = QWidget(top)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        name_row = QWidget(left)
        name_row_layout = QHBoxLayout(name_row)
        name_row_layout.setContentsMargins(0, 0, 0, 0)
        name_row_layout.addWidget(_label(name_row, f"{spec.label} details", F_ITEM_TITLE, TEXT))
        name_row_layout.addWidget(_label(name_row, f"   {spec.size}", F_SMALL, TEXT_MUTED))
        name_row_layout.addStretch(1)
        left_layout.addWidget(name_row)
        left_layout.addWidget(_rating_widget(left, spec.quality, spec.speed))
        top_layout.addWidget(left, 1)
        container_layout.addWidget(top)

        container_layout.addWidget(autowrap_label(
            container,
            f"Gated on Hugging Face ({SAM3_HF_REPO_ID}) — request access, wait for approval, then "
            "paste a READ token below. The token is only checked against the repo once the plan "
            "actually runs, so queuing it now is free.",
            fg=TEXT_MUTED, bg=CARD_BG, font=F_SMALL))

        row1 = QWidget(container)
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.addWidget(RoundedButton(row1, "Request access on Hugging Face", icon="link",
                                             variant="secondary", width=270,
                                             command=lambda: webbrowser.open(SAM3_HF_PAGE)))
        row1_layout.addStretch(1)
        container_layout.addWidget(row1)

        row2 = QWidget(container)
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.addWidget(_label(row2, "HF token", F_BODY_B, TEXT))
        hf_entry = QLineEdit(row2)
        hf_entry.setEchoMode(QLineEdit.Password)
        hf_entry.setFixedWidth(300)
        row2_layout.addWidget(hf_entry)
        self._hf_token_entry = hf_entry

        if installed:
            sam3_btn = RoundedButton(row2, "Remove", icon="trash", variant="danger", width=130)

            def toggle_sam3():
                self.plan.toggle(PlannedAction(remove_key, "Remove SAM 3", "remove",
                                                lambda job: remove_sam3(job)))
                self._sync_sam_setup_in_plan()
                self.refresh_sam_page()

            self._wizard_cards["sam3"] = toggle_sam3
            sam3_btn.command = toggle_sam3

            def refresh(present: bool = True):
                q = self.plan.has(remove_key)
                sam3_btn.set_text("Remove" + (" ✓" if q else ""))
        else:
            sam3_btn = RoundedButton(
                row2, "Add to plan", icon="install", variant="success", width=140,
                on_blocked=lambda: show_snackbar(self, "Enter a Hugging Face token first", tone="warn"))

            def token_entered() -> bool:
                return bool(self.hf_token_var.get().strip())

            def toggle_sam3():
                self.plan.toggle(PlannedAction(install_key, "Download SAM 3", "install",
                                                lambda job: self._run_sam3_download(job)))
                self._sync_sam_setup_in_plan()
                self.refresh_sam_page()

            self._wizard_cards["sam3"] = toggle_sam3
            sam3_btn.command = toggle_sam3

            def refresh(present: bool = True):
                queued = self.plan.has(install_key)
                sam3_btn.set_enabled(queued or token_entered())
                sam3_btn.set_text("Add to plan" + (" ✓" if queued else ""))

            def on_token_changed(text):
                self.hf_token_var.set(text)
                if self.plan.has(install_key):
                    self.plan.add(PlannedAction(install_key, "Download SAM 3", "install",
                                                 lambda job: self._run_sam3_download(job)))
                refresh(True)

            hf_entry.textChanged.connect(on_token_changed)

        row2_layout.addWidget(sam3_btn)
        row2_layout.addStretch(1)
        container_layout.addWidget(row2)

        self._sam_model_widgets.append((card, None, spec, installed))
        card._sam3_refresher = refresh

        refresh(True)
        card.finalize()
        return {
            "card_widget": card,
            "arrow_label": arrow_label,
            "container": container,
            "update_badges": update_sam3_badges,
        }

    def refresh_sam_page(self):
        for card, right_icon_label, spec, _installed_snapshot in self._sam_model_widgets:
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
            right_icon_label.setPixmap(render_icon_pixmap(rik, ric, 28))
            card._update_style()

        expanded_key = self._sam_expanded_family
        for fkey, fam_info in self._sam_family_cards.items():
            if "update_badges" in fam_info:
                fam_info["update_badges"](fkey == expanded_key)

    # ------------------------------------------------------------------
    # Review & install
    # ------------------------------------------------------------------

    def _wizard_render_review(self, parent):
        layout = parent.layout()
        self._review_rows_discard_commands = []

        if len(self.plan) == 0:
            card = RoundedCard(parent)
            layout.addWidget(card)
            card_layout = QVBoxLayout(card.body)
            card_layout.addWidget(_label(
                card.body, "Nothing queued yet — go back and pick at least one action.",
                F_BODY, TEXT_MUTED))
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
            row = RoundedCard(parent, pad=10, radius=12)
            layout.addWidget(row)
            body_layout = QVBoxLayout(row.body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            line = QWidget(row.body)
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(4, 2, 4, 2)
            line_layout.setSpacing(10)
            body_layout.addWidget(line)

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

            line_layout.addWidget(icon_label(line, left_icon, color=ACCENT, size=24))
            line_layout.addWidget(_label(line, label, F_BODY_B, TEXT), 1)

            status_icon = "check" if kind == "install" else "trash"
            status_color = SUCCESS if kind == "install" else DANGER
            line_layout.addWidget(icon_label(line, status_icon, color=status_color, size=20))

            def discard_cmd(keys=keys):
                self._wizard_discard_many(keys)
            self._review_rows_discard_commands.append(discard_cmd)

            trash_btn = RoundedButton(line, "", icon="trash", variant="danger", width=34, height=34, radius=17,
                                       command=discard_cmd)
            line_layout.addWidget(trash_btn)

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
        layout.addStretch(1)

        proceed_btn = RoundedButton(parent, f"Proceed to installation ({len(self.plan)})", icon="bolt",
                                     variant="primary", width=340, height=44,
                                     command=self._wizard_start_install)
        layout.addWidget(proceed_btn, alignment=Qt.AlignHCenter)
