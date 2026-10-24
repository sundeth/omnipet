"""Reading module data that was written under an older, misspelled key.

Three fields shipped with a spelling mistake and have since been corrected:

    avaliability                    -> availability
    jogress_avaliable               -> jogress_available
    battle_atribute_advantage       -> battle_attribute_advantage

The modules in this repo were migrated with the rename, but a module built by
someone else, or an older copy still sitting on a player's device, can carry
either spelling.  Every read of one of these fields goes through here and
prefers the correct key, so both keep working.

The Module Editor does the same on load and writes only the corrected name,
so opening and saving an old module migrates it -- the way the legacy
``ruleset`` field is already handled by ``game_module.LEGACY_RULESET_RULES``.
"""

# correct key -> the misspelling it replaced
LEGACY_KEYS = {
    "availability": "avaliability",
    "jogress_available": "jogress_avaliable",
    "battle_attribute_advantage": "battle_atribute_advantage",
    "battle_attribute_advantage_power": "battle_atribute_advantage_power",
}


def get_data(data, key, default=None):
    """``data.get(key, default)`` honouring the old misspelling of ``key``."""
    if key in data:
        return data[key]
    legacy = LEGACY_KEYS.get(key)
    if legacy is not None and legacy in data:
        return data[legacy]
    return default


def availability(data):
    """A monster record's availability.

    "Normal" (the default), "Unobtainable" (never shown in the digidex) or
    "Friend" (listed separately, and read by the DigiXros requirements).
    """
    return get_data(data, "availability") or "Normal"
