'''
import_secrets.py
Import secrets into variables

Ported from upstream. Upstream opens `secrets.json` relative to the working
directory, which on a CircuitPython device is the root of the drive the
player drops the file onto. Omnipet has a save directory instead -- and on
Android that is `app_storage_path()/save`, nowhere near the working
directory -- so the file is looked for in both places.

The module-level names are upstream's, unchanged, because `mqtt.py` is
vendored verbatim and reads them directly.
'''

import json
import os

#: Where the file is looked for, in order. The save directory comes first so
#: a player's own credentials win over anything shipped beside the game.
SECRETS_FILENAME = "secrets.json"

secrets_wireless_networks = ""
secrets_user_uuid = ""
secrets_device_uuid = ""
secrets_mqtt_broker = ""
secrets_mqtt_username = ""
secrets_mqtt_password = ""
secrets_imported = False
secrets_error = ""
secrets_error_display = ""
secrets_path = None


def candidate_paths():
	'''
	The paths `secrets.json` is looked for in, in order.
	'''
	paths = []
	try:
		from core.game_globals import _get_base_save_dir
		paths.append(os.path.join(_get_base_save_dir(), SECRETS_FILENAME))
	except Exception:
		paths.append(os.path.join("save", SECRETS_FILENAME))
	# Upstream's own location, so a file copied straight from the WiFiCom
	# docs next to the game still works.
	paths.append(SECRETS_FILENAME)
	return paths


def find_secrets():
	'''
	The first candidate path that exists, or None.
	'''
	for path in candidate_paths():
		if os.path.isfile(path):
			return path
	return None


def reload():
	'''
	Re-read the secrets file and update the module-level values.

	Returns True if they were imported. Called at import time, and again by
	the service when the player may have added the file since.

	Note this does not reach `mqtt.py`, which builds its topic strings once
	at import time from these values -- see `services/wificom_service.py`,
	which imports `mqtt` only after this has succeeded.
	'''
	#pylint:disable=global-statement
	global secrets_wireless_networks, secrets_user_uuid, secrets_device_uuid
	global secrets_mqtt_broker, secrets_mqtt_username, secrets_mqtt_password
	global secrets_imported, secrets_error, secrets_error_display, secrets_path

	secrets_imported = False
	secrets_error = ""
	secrets_error_display = ""
	secrets_path = find_secrets()

	if secrets_path is None:
		secrets_error = "secrets.json cannot be loaded, " + \
			"please copy and edit from webapp or secrets.example.json"
		secrets_error_display = "No credentials"
		return False

	try:
		with open(secrets_path, encoding="utf-8") as json_file:
			secrets = json.load(json_file)

		secrets_wireless_networks = secrets.get("wireless_networks", [])
		secrets_user_uuid = secrets["user_uuid"]
		secrets_device_uuid = secrets["device_uuid"]
		secrets_mqtt_broker = secrets["broker"]
		secrets_mqtt_username = secrets["mqtt_username"]
		secrets_mqtt_password = secrets["mqtt_password"]

		secrets_imported = True

	except OSError as e:
		secrets_error = f"Error reading {secrets_path}: {str(e)}"
		secrets_error_display = "Cannot read secrets"
	except ValueError:
		secrets_error = "Syntax error in secrets.json"
		secrets_error_display = "Bad secrets file"
	except KeyError as e:
		secrets_error = "Missing field in secrets.json: " + str(e)
		secrets_error_display = "Secrets missing " + str(e)

	return secrets_imported


reload()
