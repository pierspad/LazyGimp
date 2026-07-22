# lazygimp/gui — PySide6 engine (Phase 1: theme + widget library)

This package is a parallel PySide6 implementation of `lazygimp/gui`
(CustomTkinter). **Nothing under `lazygimp/gui/` was touched** — the Tk
GUI is still what actually ships/launches until a later phase swaps it
in. This phase only builds the foundation: design tokens, the reusable
widget library, icons, and dialogs. No page module
(landing/uninstall/wizard/progress) has been ported yet — that's the
next phase(s), building on the API below.

Every color hex code is copied verbatim from `lazygimp/gui/theme.py`.
This is a toolkit swap, not a redesign.

## The one big structural difference: layout

Tk's `pack()`/`grid()` auto-flow with no parent-side declaration. Qt
widgets need an explicit `QLayout` set on their parent before children
show up. This is NOT hidden by this library — page-porting agents will
write real `QVBoxLayout`/`QHBoxLayout`/`QGridLayout` calls where the old
code called `.pack(...)`/`.grid(...)`. Two conventions carry over
directly, though:

- `RoundedCard.body` / `ScrollableFrame.inner` are still the plain
  container children get added to — just remember to give them a layout
  first: `QVBoxLayout(card.body)`, then `layout.addWidget(child)`.
- `page_header()` and `callout()` auto-append themselves to
  `parent.layout()` if the parent already has one (mirroring the old
  auto-pack convenience) — everything else needs an explicit
  `layout.addWidget(...)`.

## theme.py

| Old (`gui/theme.py`) | New (`gui/theme.py`) | Notes |
|---|---|---|
| `BG`, `CARD_BG`, `CARD_BORDER`, `TEXT`, `TEXT_MUTED`, `ACCENT`, `ACCENT_HOVER`, `ACCENT_TEXT`, `SUCCESS`, `SUCCESS_HOVER`, `SUCCESS_TEXT`, `DANGER`, `DANGER_HOVER`, `DANGER_TEXT`, `WARNING`, `DISABLED_BG`, `DISABLED_TEXT`, `FIELD_BG`, `SCROLLBAR`, `LOG_BG`, `SECONDARY_HOVER` | same names, same hex values | identical, re-exported |
| `TONE_COLORS` | same | identical dict |
| `F_HERO` ... `F_MONO` | same names, same `(family, size, weight)` tuples | pass through `qfont()` when a Qt widget needs a `QFont` |
| `ICON_SIZE` | same | identical |
| `apply_style(root)` | `build_stylesheet()` | Tk's version configured a ttk style object in place; Qt has no in-place "style engine" to configure — call `app.setStyleSheet(theme.build_stylesheet())` once on the `QApplication` instead. Per-instance look (button variant colors, card radius/hover) lives in `widgets.py`, same split of responsibility as before. |
| — | `qfont(spec)` | new: `(family, size, weight)` tuple -> `QFont`. |
| — | `qcolor(hexstr)` | new: hex string -> `QColor`, convenience only. |

## widgets.py

| Old (`gui/widgets.py`) | New (`gui/widgets.py`) | Behavior differences |
|---|---|---|
| `RoundedButton(parent, text, command=, variant=, icon=, width=, height=, radius=, font=, bg=, on_blocked=)` | same signature, same kwargs | Icon is a real `QIcon` in the button's icon slot (via `setIcon`), not a text glyph spliced into the label — Qt buttons don't need the Tk engine's `_BUTTON_GLYPHS` text fallback since `render_icon()` never needs an optional Pillow dependency. `.command`, `.text` properties, `set_text()`, `set_enabled()`, `set_variant()`, `start_loading()`/`stop_loading()` all present with identical names/semantics. `on_blocked` still fires when a disabled button is clicked (via an `event()` override, since Qt — like Tk — normally swallows clicks on disabled widgets entirely). |
| `RoundedCard(parent, bg=, border=, radius=, pad=, width=, height=, command=, hover_bg=, hover_border=, active_border=, active_width=)` | same signature | `.body` is a plain `QWidget` (was `tk.Frame`) — give it a layout before adding children. `finalize()` still wires up hover/click across the whole subtree (needed for the same reason as Tk: mouse events go to whichever child is under the pointer, not the card), implemented as one `QObject` event filter installed recursively instead of Tk's recursive `<Enter>/<Leave>/<Button-1>` binding. Background propagation to children is automatic in Qt (plain `QWidget`s are transparent by default) — no `_set_bg_recursive` equivalent needed. |
| `ProgressBar(parent, width=, height=, bg=, track=, fill=)` | same signature | `set_fraction()` identical. Internally uses a 0–1000 integer range instead of Tk's 0.0–1.0 float `CTkProgressBar.set()`; irrelevant to callers. |
| `ModernCheckbox(parent, variable, command=, size=, bg=, text=, font=, text_color=)` | same signature | `variable` now accepts any object with `get()`/`set()` — pass a `BoolVar` (new, see below) instead of a `tk.BooleanVar`. Synced bidirectionally on toggle. |
| `ScrollableFrame(parent, bg=)` | same signature | **`.inner` is a distinct content `QWidget`, not the frame itself** (Tk: `self.inner = self`, because `CTkScrollableFrame` is its own content surface; Qt's `QScrollArea` requires a separate content widget via `setWidget()`). Add a layout to `.inner`, add children to that layout. Mouse-wheel scrolling is native to `QScrollArea` — the Tk engine's manual `_mouse_wheel_all` platform-branching is gone, not needed. `page_up()`/`page_down()` present, same names. |
| `bind_click_recursive(widget, handler, skip=())` | same signature | Implemented via one `QObject` event filter installed on `widget` + every descendant (`findChildren(QWidget)`), same idea as Tk's recursive bind. |
| `page_header(parent, title)` | same signature | Auto-appends to `parent.layout()` if present (see layout note above); returns the `QLabel` either way. |
| `callout(parent, text, tone="info")` | same signature | Same tones (`info`/`warn`/`ok`, plus `error` added for completeness). Auto-appends to `parent.layout()` if present. |
| `autowrap_label(parent, text, fg=, bg=, font=, justify=)` (was in `gui/helpers.py`) | moved into `gui/widgets.py`, same name | Uses native `QLabel.setWordWrap(True)` — Qt wraps to its own available width automatically; the Tk version needed a hand-rolled `<Configure>` handler to fake that. `justify` takes a `Qt.AlignLeft`/`Qt.AlignRight`/etc constant instead of a `"left"`/`"right"` string. |
| — | `BoolVar` | new: minimal `get()`/`set()` box standing in for `tk.BooleanVar`, since Qt's `QCheckBox` has no `variable=` concept of its own. Use it with `ModernCheckbox`. |
| `rating_widget(...)` (in `gui/helpers.py`) | **not ported** | Not referenced by anything in scope for this phase (theme/widgets/icons/dialogs); port it alongside whichever page module needs it if one does. |

## icons.py

| Old (`gui/icons.py`) | New (`gui/icons.py`) | Notes |
|---|---|---|
| `_paint_icon(...)` geometry (per-icon-kind coordinate math) | same math, same icon-kind strings, ported almost line-for-line | Every icon kind from the Tk set is implemented: `gear, circle, appimage, gimp, photogimp, gmic, batcher, arch, debian, ubuntu, fedora, opensuse, linux, bolt, link, trash, install, folder, undo, warn, info, check, x, refresh, spinner, box`, plus `download` as an explicit alias of `trash`'s branch (kept only so an unqualified call with that name doesn't silently no-op). Not pixel-identical — Qt's stroke joins/caps render slightly differently under `QPainter` antialiasing than Tk-Canvas/Pillow did — but same silhouette, same visual language, per the task brief. |
| `render_icon_photo(kind, color, size, frame)` (PIL path) | `render_icon_pixmap(kind, color, size, frame)` | Returns a cached `QPixmap` instead of a `PIL`-backed `PhotoImage`. Always succeeds — no `_PIL_OK` guard, since Qt/QPainter is never optional in this engine. |
| `render_ctk_image(kind, color, size, frame)` | `render_icon(kind, color, size, frame)` | Returns a `QIcon` (for `QPushButton.setIcon()`) instead of a `CTkImage`. |
| `draw_icon(canvas, cx, cy, kind, color, s, frame)` | `paint_icon_on(painter, cx, cy, kind, color, s, frame)` | Draws directly with an already-open `QPainter` (e.g. inside a custom `paintEvent`) instead of onto a Tk `Canvas`. |
| `blit_icon(canvas, cx, cy, kind, color, size, frame)` | folded into `render_icon_pixmap` + `paint_icon_on` | No PIL-missing fallback branch needed (see above), so the Tk engine's photo-vs-draw fallback dance collapses to "always render a pixmap." |
| `icon_canvas(parent, kind, color, size, bg)` | `icon_label(parent, kind, color, size)` | Returns a `QLabel` with the icon pixmap set (transparent background) instead of a Tk `Canvas`. `bg` param dropped — Qt `QLabel` backgrounds are transparent by default, no need to match a parent's bg color explicitly. |

## dialogs.py

| Old (`gui/dialogs.py`) | New (`gui/dialogs.py`) | Notes |
|---|---|---|
| `themed_dialog(root, title, message, kind="info")` | same signature (`root` -> any parent `QWidget`) | Tk built its own overlay + borderless `Toplevel` + manual click-outside/`<Configure>`-tracking by hand. Qt uses a real frameless modal `QDialog` instead — centering-on-parent and blocking-until-closed come from Qt's own dialog/event-loop machinery (`exec()`), not hand-rolled geometry tracking. Same return convention: `True`/`False`. |
| `themed_info(root, title, message)` | same signature | Same behavior. |
| `themed_confirm(root, title, message)` | same signature | Same behavior. |
| `show_snackbar(app, message, tone="warn", duration_ms=2200)` | same signature | `app` is expected to expose `.window` (falls back to `.root` for a transitional app object that has both). Auto-closes via `QTimer.singleShot` instead of Tk's `.after`. |
| `TkPasswordPrompt(root)` | `QPasswordPrompt(window)` (alias `TkPasswordPrompt` also exported) | Same calling convention: construct once on the GUI thread with the top-level window, then call the **instance** with a prompt string from any thread — it blocks and returns the password string. Internally uses a Qt signal (`Qt.QueuedConnection`) + `threading.Event` to marshal the dialog onto the GUI thread and block the calling (worker) thread for the result — the direct Qt-native equivalent of the Tk version's `root.after(0, ask)` + `threading.Event` dance. |

## Icons/theme sandbox note (for whoever runs this next)

This sandbox has no system `libEGL`/`libGL` and no `sudo`. PySide6
imports `QtGui`/`QtWidgets` unconditionally against those libs even with
`QT_QPA_PLATFORM=offscreen`. Fix used here (no root required):

```sh
cd ~ && apt-get download libegl1 libgl1 libglx0 libopengl0 libxkbcommon0 \
    libxcb-cursor0 libgbm1 libglx-mesa0
mkdir -p localdeb
for f in *.deb; do dpkg-deb -x "$f" localdeb; done
export LD_LIBRARY_PATH=$HOME/localdeb/usr/lib/x86_64-linux-gnu
export QT_QPA_PLATFORM=offscreen
```

`apt-get download` fetches `.deb`s without installing/root; `dpkg-deb -x`
extracts them to a plain directory; `LD_LIBRARY_PATH` makes the loader
find them without touching the system.

## Running the smoke test

```sh
LD_LIBRARY_PATH=$HOME/localdeb/usr/lib/x86_64-linux-gnu \
QT_QPA_PLATFORM=offscreen \
python3 -m lazygimp.gui._smoke_test
```

Builds one of every widget/dialog in a real `QApplication` and asserts
none of them raise. It does **not** verify visual correctness (there's
no display in this sandbox) — eyeball the real window on a machine with
a display before trusting this foundation for the page ports.

## Explicitly out of scope for this phase

- Any page module (`landing.py`, `uninstall.py`, `wizard.py`,
  `progress.py`) — next phase(s) build those on top of this API.
- Wiring `gui` into `lazygimp/cli.py` / `launch_gui()` — the Tk GUI
  is still what actually launches.
- Packaging fallout from dropping the zero-binary-dependency zipapp
  story — a separate task.
