'''
version.py
Handles the version info reported to wificom.dev.

Ported from upstream. Upstream reads the board id from `board` and the
firmware string from `os.uname()`, neither of which exists off CircuitPython,
and pulls the name/version from the repo-root `version_info.py` that the
WiFiCom build CI rewrites. Omnipet has no such build step, so those three
constants live here instead.

The dictionary keys are upstream's and must stay upstream's: the server reads
them off every message a WiFiCom publishes. Only the values change, and they
say what Omnipet actually is rather than claiming a board it is not.
'''

import collections
import platform
import sys

#: Upstream's `version_info.name`. This is the protocol identity the server
#: knows, so it stays "wificom" -- Omnipet is presenting itself as one.
NAME = "wificom"
#: Which wificom-lib release this package was vendored from, plus who is
#: running it. Bump the first half when re-syncing against upstream.
VERSION = "2.1.0-omnipet"
#: Upstream's `version_info.variant`, which distinguishes builds of the same
#: version.
VARIANT = "omnipet"
#: What upstream would report as `board.board_id`.
BOARD_ID = "omnipet"

_has_display = None
def set_display(value):
	'''
	Set whether we have a display.
	'''
	global _has_display  #pylint:disable=global-statement
	_has_display = value

_settings = None
def set_settings(obj):
	'''
	Link the settings object.
	'''
	global _settings  #pylint:disable=global-statement
	_settings = obj

def _runtime():
	'''
	The string reported where upstream reports the CircuitPython build.
	'''
	python_version = sys.version.split()[0]
	return f"Python {python_version} on {platform.system()}"

def dictionary():
	'''
	Convert version info to an OrderedDict.
	'''
	result = collections.OrderedDict()
	result["name"] = NAME
	result["version"] = VERSION
	result["circuitpython_version"] = _runtime()
	result["circuitpython_board_id"] = BOARD_ID
	result["has_display"] = _has_display
	if _settings is not None:
		result["turn_1_button"] = _settings.turn_1_button
	return result

def _toml_value(value):
	if value is True:
		return 'true'
	elif value is False:
		return 'false'
	else:
		return f'"{value}"'

def toml():
	'''
	Convert version info to a TOML string.
	'''
	dic = dictionary()
	items = [f'{key} = {_toml_value(dic[key])}' for key in dic]
	return "\r\n".join(items)

def onscreen():
	'''
	Create version info for display on the screen.
	'''
	version = VERSION
	if len(version) <= 12:
		version = "WiFiCom: " + version
	return f"{version}\n{_runtime()}\n{BOARD_ID}"
