## [2.2.1](https://github.com/pierspad/LazyGimp/compare/v2.2.0...v2.2.1) (2026-07-23)

### 🐛 Bug Fixes

* **windows:** resolve termios/pty import error on Windows and simplify release asset names ([41b08cb](https://github.com/pierspad/LazyGimp/commit/41b08cbdc401b4c9599343dad35b3160cdb92f52))

## [2.2.0](https://github.com/pierspad/LazyGimp/compare/v2.1.1...v2.2.0) (2026-07-23)

### ✨ Features

* **cross-platform:** enhance Windows support and add photogimp/gimp_detect unit test suite ([9be43e9](https://github.com/pierspad/LazyGimp/commit/9be43e927bf66329fac2ee7945cc6df55c781861))

## [2.1.1](https://github.com/pierspad/LazyGimp/compare/v2.1.0...v2.1.1) (2026-07-23)

### 🐛 Bug Fixes

* **desktop:** resolve desktop entry retargeting and sessionrc parsing ([4800490](https://github.com/pierspad/LazyGimp/commit/4800490245f8bc6726ed9c56bbe4d9bb1886d1e6))

## [2.1.0](https://github.com/pierspad/LazyGimp/compare/v2.0.0...v2.1.0) (2026-07-23)

### ✨ Features

* **gui-qt:** port install-progress page to PySide6 ([bbfe364](https://github.com/pierspad/LazyGimp/commit/bbfe3643523a559f649996c59a36efd557fb02e0))
* **gui-qt:** port landing and uninstall pages to PySide6 ([3ebec9f](https://github.com/pierspad/LazyGimp/commit/3ebec9f1e8fb80214e09a411a4f741bdfa7514a7))
* **gui-qt:** port wizard flow to PySide6 ([8e57917](https://github.com/pierspad/LazyGimp/commit/8e579177cf07898135ab0c6e0627e9bb17bff116))
* **gui-qt:** PySide6 theme + widget library foundation ([5110857](https://github.com/pierspad/LazyGimp/commit/51108575f327e386ac08051a47c5d1e0e01990df))
* **gui-qt:** wire up LazyGimpApp and --qt entrypoint ([8d011db](https://github.com/pierspad/LazyGimp/commit/8d011db7c320ea621adb3e3ee45f10792aed5e93))
* **gui:** allow toggling removal on already-installed components in wizard ([1f8f0ba](https://github.com/pierspad/LazyGimp/commit/1f8f0baee7603e8cd121ca03859fdc5398eefcdb))
* **gui:** complete PySide6 migration, redesign installer UI and update PyTorch wheel indexes ([e767427](https://github.com/pierspad/LazyGimp/commit/e767427f30cd666979a6cc922a1f20f1342ef0ec))
* **gui:** fix card clicks, filter PyTorch builds by GPU, sanitize step order and refine terminal log styling ([d960447](https://github.com/pierspad/LazyGimp/commit/d960447050bc31516cfc2043b9a604674d3d90de))
* **gui:** interactive per-step cards on the install-progress screen ([15ff390](https://github.com/pierspad/LazyGimp/commit/15ff3901078cfed30cae8238bebd9b0ceffb6637))
* **gui:** stack snackbar toasts vertically with countdown progress bar ([b03dd7b](https://github.com/pierspad/LazyGimp/commit/b03dd7b6f93ee8dad366c59edb0b5aba33b61288))

### 🐛 Bug Fixes

* **ci:** fix requirements file missing error and cancel concurrent obsolete builds ([6a69f6f](https://github.com/pierspad/LazyGimp/commit/6a69f6f29b994e23bc8093177a5748941ee74caa))
* **gimp:** surface a diagnostic tip for a stale pacman db lock ([f7a6143](https://github.com/pierspad/LazyGimp/commit/f7a61435f7729c9152d29c65fbd2a30d7eb66f87))
* **gimp:** warm up GIMP with a real GUI pass, not just console mode ([750cf06](https://github.com/pierspad/LazyGimp/commit/750cf06dcaf248a202055e18719bdadf7456ac76))
* **gui:** fix mouse-wheel crash from a renamed CustomTkinter API ([eac3e79](https://github.com/pierspad/LazyGimp/commit/eac3e7910e9ca6be37af9c1c407300ede471d6dc))
* **gui:** round scrollbars, remove log header border box, protect installed components, and widen buttons ([0aa62da](https://github.com/pierspad/LazyGimp/commit/0aa62daf1a32f3ff1a4bd610c3b3432bb99820a0))
* PhotoGIMP now working and headless warm-up enabled ([5c8b9a0](https://github.com/pierspad/LazyGimp/commit/5c8b9a078420ba8bf4946cc1c09ead2ef294443a))
* **photogimp:** apply PhotoGIMP across all GIMP profile dirs and enhance running process detection ([70dfbe6](https://github.com/pierspad/LazyGimp/commit/70dfbe63bd545522e61c7748c06c359d43ac0975))
* **photogimp:** don't let GIMP clobber PhotoGIMP's config, fetch latest commit ([32917a5](https://github.com/pierspad/LazyGimp/commit/32917a557ab06f697c3285932344e7e294e7ca5b))

## [2.0.0](https://github.com/pierspad/LazyGimp/compare/v1.1.2...v2.0.0) (2026-07-20)

### ⚠ BREAKING CHANGES

* lazygimp no longer contains the SAM implementation;
running from a bare git checkout without a sibling GIMPSAM checkout
needs network on first SAM use (release artifacts are unaffected —
they vendor gimpsam).
* the shell installers (install.sh,
package-manager-install.sh, appimage-install.sh, plugins-install.sh,
uninstall.sh, lib/, shell_scripts/) and the lazygimp.tar.gz bundle are
gone — use the python entry points instead.

### ✨ Features

* add shortcuts, preselected defaults, collapsible categories, and overlay stacking fixes ([fd87fb5](https://github.com/pierspad/LazyGimp/commit/fd87fb57d10f0d6f0e4efd5a0e21f977af718f8c))
* aggregate SAM from the pinned gimpsam package instead of reimplementing it ([8b9b6e2](https://github.com/pierspad/LazyGimp/commit/8b9b6e2e66099438a9f0fb2bed6e8266aae9609a))
* **gui:** bigger crisper UI, merged components page, installer.py rename ([2325fd0](https://github.com/pierspad/LazyGimp/commit/2325fd0ffe1ac082f79ad995292f26484641e6a7))
* **gui:** implement 4x scroll speed, expand viewport, make SAM cards clickable and center proceed button ([18ad489](https://github.com/pierspad/LazyGimp/commit/18ad4893635e077b9ad2895a807ba8bd2f14c51c))
* **gui:** implement global keyboard shortcuts for full hands-free installer navigation ([6cbde67](https://github.com/pierspad/LazyGimp/commit/6cbde675dadcaeb91ee1f92b4ce4a0be40f6257d))
* **gui:** improve installer aesthetics, add custom vector icons and automate SAM setup ([97bae73](https://github.com/pierspad/LazyGimp/commit/97bae734d34da76c201a5a28cae2b02d85ab06a1))
* **gui:** keep headers/footers static during transition, add gimp icon, improve dialog corners and review list layout ([adfaa5b](https://github.com/pierspad/LazyGimp/commit/adfaa5bd1003180c9d3af832796af6da07b8c9c6))
* **gui:** modern CustomTkinter interface + self-deleting installer option ([bc80f6e](https://github.com/pierspad/LazyGimp/commit/bc80f6eba8752ee1907c4607a9d7021740a70292))
* **gui:** pre-render wizard pages in memory to eliminate step transition lag ([68f0b48](https://github.com/pierspad/LazyGimp/commit/68f0b486318e011889198bccfc8df1158f004167))
* **gui:** smooth landing→wizard transition + SAM header badges ([e64762a](https://github.com/pierspad/LazyGimp/commit/e64762a8dfebd0db81c50a5872370ef02610adfc))
* implement GIMP prerequisite layout, arrow navigation, PageUp/PageDown, and category/model shortcuts ([83075cc](https://github.com/pierspad/LazyGimp/commit/83075cc0bee862d09c64da01a60091bfc21e14a0))
* replace the shell-script bundle with a python package ([89b2860](https://github.com/pierspad/LazyGimp/commit/89b28601f8fbc263ed58b53084de750854a704dd))
* take gimpsam from GIMPSAM's latest official release instead of a pinned SHA ([9a9b759](https://github.com/pierspad/LazyGimp/commit/9a9b759a8463496b426467809abcad194986fb9c))

### 🐛 Bug Fixes

* **ci:** authenticate GitHub API curl to avoid rate-limit (exit 22) ([011c5ba](https://github.com/pierspad/LazyGimp/commit/011c5bad9236f2bf58a59f62a7e261846052bf47))
* GIMP prereq cards use (1)/(2) in TEXT color; SAM families build once and repack for flicker-free toggling; SAM headers in TEXT color with (N) shortcuts; model shortcuts show [Shift N] ([9d51e73](https://github.com/pierspad/LazyGimp/commit/9d51e73a1a50aadeb2d50e7e2ac0357abe55abeb))
* **gui:** fix linter errors, import DISABLED theme colors, and remove unused variables ([bf78e20](https://github.com/pierspad/LazyGimp/commit/bf78e2047922977491acabf17ac50cd57ef0eeaa))
* **release:** find README/LICENSE wherever they live (docs/ or root) ([ff15124](https://github.com/pierspad/LazyGimp/commit/ff1512472223ba1beb7c18d969636b62627270f9))
* **release:** honor BREAKING CHANGE over the custom release rules ([a538385](https://github.com/pierspad/LazyGimp/commit/a538385e4b6d1bcc2dea8b8ce9f9c7053b55568a))
* **release:** ship release assets under their plain file names ([a6d10b5](https://github.com/pierspad/LazyGimp/commit/a6d10b5b8ca80397766c57574e7b235878b1c9e9))
* remove unused imports/vars (ruff F401/F841); add explicit --hidden-import for all gimpsam submodules in PyInstaller build; pre-commit hook finds pipx-installed ruff ([dd1e453](https://github.com/pierspad/LazyGimp/commit/dd1e453012a94b2bddaca813dae5be69d261fc6c))
* resolve NameError for F_ITEM_TITLE and fix black overlay bug on Linux ([c4fcd91](https://github.com/pierspad/LazyGimp/commit/c4fcd91fed5577eacebba6437f53a35efcbe9602))

### ♻️ Refactoring

* **gui:** split the Tk GUI into a modular package with incremental rendering ([78a4674](https://github.com/pierspad/LazyGimp/commit/78a4674e8d169d356a3f805f4e3937b4b94fa22b))

## [2.0.0-dev.6](https://github.com/pierspad/LazyGimp/compare/v2.0.0-dev.5...v2.0.0-dev.6) (2026-07-20)

### ✨ Features

* **gui:** smooth landing→wizard transition + SAM header badges ([e64762a](https://github.com/pierspad/LazyGimp/commit/e64762a8dfebd0db81c50a5872370ef02610adfc))

### 🐛 Bug Fixes

* **ci:** authenticate GitHub API curl to avoid rate-limit (exit 22) ([011c5ba](https://github.com/pierspad/LazyGimp/commit/011c5bad9236f2bf58a59f62a7e261846052bf47))

## [2.0.0-dev.5](https://github.com/pierspad/LazyGimp/compare/v2.0.0-dev.4...v2.0.0-dev.5) (2026-07-19)

### 🐛 Bug Fixes

* remove unused imports/vars (ruff F401/F841); add explicit --hidden-import for all gimpsam submodules in PyInstaller build; pre-commit hook finds pipx-installed ruff ([dd1e453](https://github.com/pierspad/LazyGimp/commit/dd1e453012a94b2bddaca813dae5be69d261fc6c))

## [2.0.0-dev.4](https://github.com/pierspad/LazyGimp/compare/v2.0.0-dev.3...v2.0.0-dev.4) (2026-07-19)

### 🐛 Bug Fixes

* GIMP prereq cards use (1)/(2) in TEXT color; SAM families build once and repack for flicker-free toggling; SAM headers in TEXT color with (N) shortcuts; model shortcuts show [Shift N] ([9d51e73](https://github.com/pierspad/LazyGimp/commit/9d51e73a1a50aadeb2d50e7e2ac0357abe55abeb))

## [2.0.0-dev.3](https://github.com/pierspad/LazyGimp/compare/v2.0.0-dev.2...v2.0.0-dev.3) (2026-07-19)

### ✨ Features

* implement GIMP prerequisite layout, arrow navigation, PageUp/PageDown, and category/model shortcuts ([83075cc](https://github.com/pierspad/LazyGimp/commit/83075cc0bee862d09c64da01a60091bfc21e14a0))

## [2.0.0-dev.2](https://github.com/pierspad/LazyGimp/compare/v2.0.0-dev.1...v2.0.0-dev.2) (2026-07-19)

### 🐛 Bug Fixes

* resolve NameError for F_ITEM_TITLE and fix black overlay bug on Linux ([c4fcd91](https://github.com/pierspad/LazyGimp/commit/c4fcd91fed5577eacebba6437f53a35efcbe9602))

## [2.0.0-dev.1](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.9...v2.0.0-dev.1) (2026-07-19)

### ⚠ BREAKING CHANGES

* lazygimp no longer contains the SAM implementation;
running from a bare git checkout without a sibling GIMPSAM checkout
needs network on first SAM use (release artifacts are unaffected —
they vendor gimpsam).

### ✨ Features

* add shortcuts, preselected defaults, collapsible categories, and overlay stacking fixes ([fd87fb5](https://github.com/pierspad/LazyGimp/commit/fd87fb57d10f0d6f0e4efd5a0e21f977af718f8c))
* aggregate SAM from the pinned gimpsam package instead of reimplementing it ([8b9b6e2](https://github.com/pierspad/LazyGimp/commit/8b9b6e2e66099438a9f0fb2bed6e8266aae9609a))
* take gimpsam from GIMPSAM's latest official release instead of a pinned SHA ([9a9b759](https://github.com/pierspad/LazyGimp/commit/9a9b759a8463496b426467809abcad194986fb9c))

## [1.2.0-dev.9](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.8...v1.2.0-dev.9) (2026-07-18)

### ✨ Features

* **gui:** pre-render wizard pages in memory to eliminate step transition lag ([68f0b48](https://github.com/pierspad/LazyGimp/commit/68f0b486318e011889198bccfc8df1158f004167))

## [1.2.0-dev.8](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.7...v1.2.0-dev.8) (2026-07-18)

### ✨ Features

* **gui:** implement global keyboard shortcuts for full hands-free installer navigation ([6cbde67](https://github.com/pierspad/LazyGimp/commit/6cbde675dadcaeb91ee1f92b4ce4a0be40f6257d))

### 🐛 Bug Fixes

* **gui:** fix linter errors, import DISABLED theme colors, and remove unused variables ([bf78e20](https://github.com/pierspad/LazyGimp/commit/bf78e2047922977491acabf17ac50cd57ef0eeaa))

## [1.2.0-dev.7](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.6...v1.2.0-dev.7) (2026-07-18)

### ✨ Features

* **gui:** implement 4x scroll speed, expand viewport, make SAM cards clickable and center proceed button ([18ad489](https://github.com/pierspad/LazyGimp/commit/18ad4893635e077b9ad2895a807ba8bd2f14c51c))

## [1.2.0-dev.6](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.5...v1.2.0-dev.6) (2026-07-18)

### ✨ Features

* **gui:** keep headers/footers static during transition, add gimp icon, improve dialog corners and review list layout ([adfaa5b](https://github.com/pierspad/LazyGimp/commit/adfaa5bd1003180c9d3af832796af6da07b8c9c6))

## [1.2.0-dev.5](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.4...v1.2.0-dev.5) (2026-07-18)

### ✨ Features

* **gui:** improve installer aesthetics, add custom vector icons and automate SAM setup ([97bae73](https://github.com/pierspad/LazyGimp/commit/97bae734d34da76c201a5a28cae2b02d85ab06a1))

## [1.2.0-dev.4](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.3...v1.2.0-dev.4) (2026-07-18)

### ✨ Features

* **gui:** bigger crisper UI, merged components page, installer.py rename ([2325fd0](https://github.com/pierspad/LazyGimp/commit/2325fd0ffe1ac082f79ad995292f26484641e6a7))
* **gui:** modern CustomTkinter interface + self-deleting installer option ([bc80f6e](https://github.com/pierspad/LazyGimp/commit/bc80f6eba8752ee1907c4607a9d7021740a70292))

### 🐛 Bug Fixes

* **release:** find README/LICENSE wherever they live (docs/ or root) ([ff15124](https://github.com/pierspad/LazyGimp/commit/ff1512472223ba1beb7c18d969636b62627270f9))

## [1.2.0-dev.3](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.2...v1.2.0-dev.3) (2026-07-18)

### 🐛 Bug Fixes

* **release:** ship release assets under their plain file names ([a6d10b5](https://github.com/pierspad/LazyGimp/commit/a6d10b5b8ca80397766c57574e7b235878b1c9e9))

### ♻️ Refactoring

* **gui:** split the Tk GUI into a modular package with incremental rendering ([78a4674](https://github.com/pierspad/LazyGimp/commit/78a4674e8d169d356a3f805f4e3937b4b94fa22b))

## [1.2.0-dev.2](https://github.com/pierspad/LazyGimp/compare/v1.2.0-dev.1...v1.2.0-dev.2) (2026-07-18)

### 🐛 Bug Fixes

* **release:** honor BREAKING CHANGE over the custom release rules ([a538385](https://github.com/pierspad/LazyGimp/commit/a538385e4b6d1bcc2dea8b8ce9f9c7053b55568a))

## [1.2.0-dev.1](https://github.com/pierspad/LazyGimp/compare/v1.1.2...v1.2.0-dev.1) (2026-07-18)

### ⚠ BREAKING CHANGES

* the shell installers (install.sh,
package-manager-install.sh, appimage-install.sh, plugins-install.sh,
uninstall.sh, lib/, shell_scripts/) and the lazygimp.tar.gz bundle are
gone — use the python entry points instead.

### ✨ Features

* replace the shell-script bundle with a python package ([89b2860](https://github.com/pierspad/LazyGimp/commit/89b28601f8fbc263ed58b53084de750854a704dd))

## [1.1.2](https://github.com/pierspad/LazyGimp/compare/v1.1.1...v1.1.2) (2026-07-05)

### 🐛 Bug Fixes

* dai ([6aeba67](https://github.com/pierspad/LazyGimp/commit/6aeba67a1014842465b9785e0bba9e7ff25b6db8))
