[app]

title = Omnipet VPet Simulator
package.name = omnipet
package.domain = org.omnipet
icon.filename = assets/icon.png
presplash.filename = assets/presplash.png

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt,ttf,wav,mp3,ogg,zip
# NOTE: ``modules/**`` and ``network/**`` are intentionally absent.
# Releases ship with an empty modules/ folder (staged by
# build_android.ps1 into the WSL build tree before buildozer runs), and
# the legacy network/ folder no longer exists in the source tree.
source.include_patterns = assets/**, src/**, *.py, *.json, *.txt, *.zip
source.exclude_dirs = tests,tmp,bin,build,utilities,Documentation,logs,Module Editor,Release,__pycache__,python-for-android
source.exclude_patterns = license,images/*/*.jpg,*.spec,*.bat,*.sh,*.ps1,*.md,*.log

version = 1.0.1

# ❗ Python 3.10 build target (3.11 has breaking changes with pygame)
# paho-mqtt is the WiFiCom transport (src/wificom/transport.py). Pure Python,
# so p4a takes it straight from PyPI without a recipe.
requirements = python3, pygame, plyer, requests, urllib3, idna, certifi, pyjnius, paho-mqtt, tzdata

p4a.bootstrap = sdl2

# Use local stable python-for-android from working project
p4a.source_dir = /home/anderporto/python-for-android

orientation = landscape
fullscreen = 1

android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE, INTERNET, POST_NOTIFICATIONS, RECEIVE_BOOT_COMPLETED

# Native scheduled notifications; no Python background service.
android.add_src = android_src
android.add_aars = android_src/pet-notifications.aar
android.add_gradle_repositories = flatDir { dirs 'libs' }
android.entrypoint = org.omnipet.offline.PetActivity

android.api = 33
android.minapi = 21
android.arch = arm64-v8a

# NDK 25b is good — no change needed
android.ndk = 25b

android.private_storage = True
android.accept_sdk_license = True

# Better compatibility
android.meta_data = com.google.android.gles.version=0x00020000
android.enable_androidx = True
android.manifest.orientation = landscape

# Buildozer section
[buildozer]
log_level = 2
warn_on_root = 1

# ❗ Use the newly installed interpreter
python3 = /usr/bin/python3.10
