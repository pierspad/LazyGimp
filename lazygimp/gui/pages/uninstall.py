"""Uninstall screen — pick components, run the removals."""

from __future__ import annotations

from ...compat import tk
from ...gimp_install import remove_gimp_appimage, remove_gimp_package_manager
from ...job import Job
from ...photogimp import remove_photogimp
from ...plugins import remove_batcher, remove_segany_plugin
from ...sam_backend import remove_sam_backend
from ..helpers import autowrap_label
from ..icons import icon_canvas
from ..state import detect_targets
from ..theme import BG, CARD_BG, DANGER, F_BODY, F_BODY_B, F_H1, F_SMALL, TEXT, TEXT_MUTED
from ..widgets import ModernCheckbox, RoundedButton, RoundedCard


class UninstallPage:
    def show_uninstall_confirm(self):
        self.current_screen = "uninstall"
        for w in self.root_frame.winfo_children():
            w.destroy()

        wrap = tk.Frame(self.root_frame, bg=BG)
        wrap.pack(fill="both", expand=True)
        self._build_status_bar(wrap)

        content = tk.Frame(wrap, bg=BG)
        content.pack(fill="both", expand=True, padx=40, pady=30)

        title_row = tk.Frame(content, bg=BG)
        title_row.pack(anchor="w")
        icon_canvas(title_row, "trash", color=DANGER, size=24).pack(side="left", padx=(0, 10))
        tk.Label(title_row, text="Uninstall LazyGimp", bg=BG, fg=TEXT, font=F_H1).pack(side="left")
        tk.Label(content, text="Choose what to remove. Personal GIMP files (brushes, scripts, settings not "
                                "shipped by PhotoGIMP) are never touched — only what LazyGimp itself installed.",
                 bg=BG, fg=TEXT_MUTED, font=F_BODY, wraplength=760, justify="left").pack(anchor="w",
                                                                                                 pady=(4, 18))

        targets = detect_targets()
        btns = tk.Frame(content, bg=BG)
        btns.pack(fill="x", pady=(20, 0), side="bottom")

        card = RoundedCard(content)
        card.pack(fill="both", expand=True)
        check_vars: list[tuple] = []
        if targets:
            for key, name, detail in targets:
                row = tk.Frame(card.body, bg=CARD_BG)
                row.pack(fill="x", pady=7, anchor="w")
                var = tk.BooleanVar(value=True)
                ModernCheckbox(row, var, command=lambda: update_confirm_label(), bg=CARD_BG).pack(
                    side="left", padx=(0, 10))
                icon_canvas(row, "trash", color=DANGER, size=18, bg=CARD_BG).pack(side="left", padx=(0, 10))
                col = tk.Frame(row, bg=CARD_BG)
                col.pack(side="left", fill="x", expand=True)
                tk.Label(col, text=name, bg=CARD_BG, fg=TEXT, font=F_BODY_B, anchor="w").pack(
                    anchor="w")
                autowrap_label(col, detail, fg=TEXT_MUTED, bg=CARD_BG, font=F_SMALL).pack(anchor="w",
                                                                                                fill="x")
                check_vars.append((var, key))
        else:
            tk.Label(card.body, text="Nothing found to remove.", bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
        card.finalize()

        RoundedButton(btns, "Cancel", variant="secondary", width=110, command=self.show_landing).pack(
            side="left")
        confirm_btn = RoundedButton(btns, "Delete selected", variant="danger", icon="trash", width=200,
                                     command=lambda: self.on_confirm_uninstall(
                                         [k for v, k in check_vars if v.get()]))
        confirm_btn.pack(side="left", padx=8)
        RoundedButton(btns, "Delete all", variant="danger", icon="trash", width=140,
                      command=lambda: self.on_confirm_uninstall([k for _, k in check_vars])).pack(side="left")

        def update_confirm_label():
            n = sum(1 for v, _ in check_vars if v.get())
            confirm_btn.set_text(f"Delete selected ({n})")
            confirm_btn.set_enabled(n > 0)

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
            if "appimage" in keys:
                remove_gimp_appimage(job)
            if "package-manager" in keys:
                if needs_root:
                    job.log("Removing native packages needs administrator rights — "
                            "a password prompt may appear below.")
                remove_gimp_package_manager(job)
            job.log("Uninstall finished.")

        self.run_in_background(task, on_done=self.show_landing)
