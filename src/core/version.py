"""The game's release version: the one place it is written.

main.py, main_profile.py and main_nuitka.py import it; the build scripts
(build/build_*.ps1) and tests/release/build_checks.py read it from this file.
buildozer.spec's `version` is Android's numeric versionName and carries only
the number part (1.0.0 for a pre-release such as "1.0.0 Beta 3").
"""

VERSION = "1.0.1"
