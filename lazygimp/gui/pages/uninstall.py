"""Uninstall screen — pick components, run the removals. PySide6 port of
``gui/pages/uninstall.py``.

Behavior is preserved exactly; only the toolkit changed. See
``lazygimp/gui/README.md`` for the old (Tk) -> new (Qt) API table this
was built against.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...gimp_install import remove_gimp_appimage, remove_gimp_package_manager
from ...job import Job
from ...photogimp import remove_photogimp
from ...plugins import remove_batcher, remove_segany_plugin
from ...sam_backend import remove_sam_backend
# state.py is pure detection logic (no Tk import) — reused as-is rather
# than duplicated/re-ported, see gui/state.py.
from ...gui.state import detect_targets
from ..icons import icon_label, render_icon_pixmap
from ..theme import ACCENT, CARD_BG, CARD_BORDER, DANGER, F_BODY, F_BODY_B, F_H1, F_SMALL, F_SMALL_B, TEXT, TEXT_MUTED, qfont
from ..widgets import BoolVar, RoundedButton, RoundedCard, autowrap_label


def _ensure_vbox(widget: QWidget) -> QVBoxLayout:
    layout = widget.layout()
    if layout is None:
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
    return layout


def _clear_root_frame(root_frame: QWidget, keep=None) -> QVBoxLayout:
    """See landing.py's identical helper for the full rationale (kept
    duplicated here rather than shared, so the two page modules stay
    self-contained while being developed/edited in parallel)."""
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


class UninstallPage:
    def show_uninstall_confirm(self):
        self.current_screen = "uninstall"
        root_layout = _clear_root_frame(self.root_frame)

        wrap = QWidget(self.root_frame)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(0)
        root_layout.addWidget(wrap, 1)

        content = QWidget(wrap)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 30, 40, 30)
        content_layout.setSpacing(0)
        # content fills all space above the status bar (added below, at
        # the very end, so it lands after content in this QVBoxLayout —
        # the Tk original built the status bar first but pinned it with
        # side="bottom", so the *call order* didn't determine the visual
        # order there the way plain QVBoxLayout stacking does here).
        wrap_layout.addWidget(content, 1)

        title_row = QWidget(content)
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)
        title_row_layout.setSpacing(10)
        title_row_layout.addWidget(icon_label(title_row, "trash", color=DANGER, size=26))
        title_lbl = QLabel("Uninstall LazyGimp", title_row)
        title_lbl.setFont(qfont(F_H1))
        title_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
        title_row_layout.addWidget(title_lbl)
        title_row_layout.addStretch(1)
        content_layout.addWidget(title_row)

        desc = autowrap_label(
            content,
            "Choose what to remove. Personal GIMP files (brushes, scripts, settings not "
            "shipped by PhotoGIMP) are never touched — only what LazyGimp itself installed.",
            fg=TEXT_MUTED, font=F_BODY,
        )
        content_layout.addSpacing(4)
        content_layout.addWidget(desc)
        content_layout.addSpacing(18)

        targets = detect_targets()

        check_vars: list[tuple] = []
        confirm_btn_holder: dict = {}
        card_refreshers: list = []

        def update_confirm_label():
            n = sum(1 for v, _ in check_vars if v.get())
            confirm_btn_holder["btn"].set_text(f"Delete selected ({n})")
            confirm_btn_holder["btn"].set_enabled(n > 0)

        def update_all_cards():
            for fn in card_refreshers:
                fn()

        if targets:
            for key, name, detail in targets:
                var = BoolVar(True)
                check_vars.append((var, key))

                def make_click_handler(v=var):
                    def toggle():
                        v.set(not v.get())
                        update_all_cards()
                        update_confirm_label()
                    return toggle

                card = RoundedCard(content, pad=12, radius=14, command=make_click_handler())
                content_layout.addWidget(card)
                card_body_layout = QVBoxLayout(card.body)
                card_body_layout.setContentsMargins(0, 0, 0, 0)

                row = QWidget(card.body)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(4, 2, 4, 2)
                row_layout.setSpacing(12)
                card_body_layout.addWidget(row)

                icon_kind = "gimp" if ("package-manager" in key or "flatpak" in key or "appimage" in key) else ("photogimp" if "photogimp" in key else ("batcher" if "batcher" in key else "bolt"))
                row_layout.addWidget(icon_label(row, icon_kind, color=ACCENT, size=28))

                col = QWidget(row)
                col_layout = QVBoxLayout(col)
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(2)
                row_layout.addWidget(col, 1)

                name_lbl = QLabel(name, col)
                name_lbl.setFont(qfont(F_BODY_B))
                name_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
                col_layout.addWidget(name_lbl)

                detail_lbl = autowrap_label(col, detail, fg=TEXT_MUTED, font=F_SMALL)
                col_layout.addWidget(detail_lbl)

                status_lbl = QLabel("", row)
                status_lbl.setFont(qfont(F_SMALL_B))
                status_lbl.setStyleSheet("background: transparent;")
                row_layout.addWidget(status_lbl)

                status_icon_lbl = icon_label(row, "trash", color=DANGER, size=24)
                row_layout.addWidget(status_icon_lbl)

                def make_update_ui(c=card, v=var, sl=status_lbl, sil=status_icon_lbl):
                    def update():
                        is_sel = v.get()
                        if is_sel:
                            c._bg = "#2e1b1d"
                            c._hover_bg = "#3b2527"
                            c._active_border = DANGER
                            c._active_width = 1.5
                            sl.setText("queued for removal")
                            sl.setStyleSheet(f"color: {DANGER}; background: transparent;")
                            sil.setPixmap(render_icon_pixmap("trash", DANGER, 24))
                        else:
                            c._bg = CARD_BG
                            c._hover_bg = "#2f323a"
                            c._active_border = None
                            c._active_width = 1
                            sl.setText("keep")
                            sl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
                            sil.setPixmap(render_icon_pixmap("circle", CARD_BORDER, 24))
                        c._update_style()
                    return update

                update_ui_fn = make_update_ui()
                card_refreshers.append(update_ui_fn)
                card.finalize()
                update_ui_fn()
        else:
            card = RoundedCard(content, pad=16, radius=14)
            content_layout.addWidget(card)
            empty_lbl = QLabel("Nothing found to remove.", card.body)
            empty_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            card.body.layout().addWidget(empty_lbl)
            card.finalize()

        content_layout.addStretch(1)

        btns = QWidget(content)
        btns_layout = QHBoxLayout(btns)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.setSpacing(8)
        content_layout.addWidget(btns)

        cancel_btn = RoundedButton(btns, "Cancel", variant="secondary", width=110, command=self.show_landing)
        btns_layout.addWidget(cancel_btn)

        confirm_btn = RoundedButton(
            btns, "Delete selected", variant="danger", icon="trash", width=200,
            command=lambda: self.on_confirm_uninstall([k for v, k in check_vars if v.get()]))
        btns_layout.addWidget(confirm_btn)
        confirm_btn_holder["btn"] = confirm_btn

        def delete_all_action():
            for v, _ in check_vars:
                v.set(True)
            update_all_cards()
            update_confirm_label()
            self.on_confirm_uninstall([k for _, k in check_vars])

        delete_all_btn = RoundedButton(
            btns, "Delete all", variant="secondary", icon="trash", width=140,
            command=delete_all_action)
        btns_layout.addWidget(delete_all_btn)

        self._build_status_bar(wrap)

        update_confirm_label()

    def on_confirm_uninstall(self, keys: list[str]):
        if not keys:
            return
        needs_root = "package-manager" in keys

        def task(job: Job):
            if "photogimp" in keys:
                remove_photogimp(job)
            if "batcher" in keys:
                remove_batcher(job)
            if "sam" in keys:
                remove_segany_plugin(job)
                remove_sam_backend(job)
            if "flatpak" in keys or "appimage" in keys:
                remove_gimp_appimage(job)
            if "package-manager" in keys:
                if needs_root:
                    job.log("Removing native packages needs administrator rights — "
                            "a password prompt may appear below.")
                remove_gimp_package_manager(job)
            job.log("Uninstall finished.")

        self.run_in_background(task, on_done=self.show_landing)
