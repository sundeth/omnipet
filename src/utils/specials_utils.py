"""
The Battle scene's Specials hub: what each party module offers.

A module's specials, in the order the hub lists them:

* ``shop``      each open shop.json shop (utils.currency_utils), with the
                shop's own icon from the module's ``icons/`` folder;
* ``password``  its codes.json codes, under the module's own name for them
                (codes.json ``title``: PEN20's are its Copymon) and icon
                (``icon``), else "Password".
* ``minigames`` a Digivice iC module's own minigames (the IC wire's): it
                opens the training scene's Bonus list. Its icon is the
                module's ``icons/minigames.png``. Offered only while one of
                the pets that would play is an iC Digimon (the training
                scene's BONUS button follows the same rule).

Only the modules of the current party's pets are listed, each once, in party
order, and only when it offers something. Another kind of special (the
Digimon Twin's Event Communications, the Accel's features) is one more block
in `module_specials` and one more branch in `SpecialsView._open`.
"""

import os
from dataclasses import dataclass, field

from battle.ic_attacks import is_ic_module, is_ic_native
from core import game_globals, runtime_globals
from utils import currency_utils
from utils.pet_utils import get_training_targets

#: The icon a special uses when its module names none.
GENERIC_ICONS = {
    "shop": os.path.join("assets", "ui", "Specials_Shop_1.png"),
    "password": os.path.join("assets", "ui", "Specials_Password_1.png"),
}


@dataclass
class Special:
    kind: str
    module: object
    title: str
    description: str
    icon_path: str
    data: dict = field(default_factory=dict)


def _module_icon(module, name, kind):
    """The module's ``icons/<name>.png``, else the kind's generic icon."""
    if name:
        file_name = name if name.lower().endswith(".png") else name + ".png"
        path = os.path.join(module.folder_path, "icons", file_name)
        if os.path.exists(path):
            return path
    return GENERIC_ICONS.get(kind, "")


def password_title(module) -> str:
    """What the module calls its codes ("Copymon"), or "Password"."""
    return (getattr(module, "passwords_title", "") or "").strip() or "Password"


def ic_players() -> list:
    """The pets that would play the iC's minigames: the training targets
    (the selected pets, or the party, that can train) that are iC Digimon --
    as scenes.scene_training.bonus_targets. A non-iC Digimon selected, with
    an iC one elsewhere in the party, could play none of them."""
    return [pet for pet in get_training_targets() if is_ic_native(pet)]


def module_specials(module) -> list:
    """Everything *module* offers in the hub, in the order it is listed."""
    if module is None:
        return []
    specials = []
    for shop in currency_utils.available_shops(module):
        count = len(currency_utils.shop_stock(module, shop))
        specials.append(Special(
            "shop", module, shop.get("name", ""),
            f"{count} item{'s' if count != 1 else ''} for {shop.get('currency', '')}.",
            _module_icon(module, shop.get("icon"), "shop"), {"shop": shop}))
    if module.has_passwords():
        title = password_title(module)
        description = ("Enter a password." if title == "Password"
                       else f"Enter a {title} code.")
        specials.append(Special(
            "password", module, title, description,
            _module_icon(module, getattr(module, "passwords_icon", ""), "password")))
    if is_ic_module(module) and ic_players():
        specials.append(Special(
            "minigames", module, "Minigames", "Play the iC's own minigames.",
            _module_icon(module, "minigames", "minigames")))
    return specials


def party_specials() -> list:
    """``[(module, [Special, ...]), ...]`` for each party module that offers
    something, in party order."""
    modules = getattr(runtime_globals, "game_modules", None) or {}
    seen, entries = set(), []
    for pet in game_globals.pet_list:
        name = getattr(pet, "module", None)
        if name in seen:
            continue
        seen.add(name)
        module = modules.get(name)
        specials = module_specials(module)
        if specials:
            entries.append((module, specials))
    return entries


def any_party_specials() -> bool:
    return bool(party_specials())
