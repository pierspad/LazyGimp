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
