# -*- coding: utf-8 -*-
"""Digimon sprite lookup exactly as the game does it (utils/sprite_utils).

Each format is looked up in the module's folder, the module's zip, the shared
assets folder, then the shared zip; the FIRST set found is the one drawn, so
an incomplete module set hides a complete shared one. Names match exactly: a
set that only matches in another letter case loads on Windows, not on Linux
or Android, and is reported apart. (From utilities/claude/audit_module_sprites.py.)
"""
import os
import re
import zipfile

from paths import ASSETS

FOLDERS = {"Color": "monsters", "Dot": "monsters_dot", "HD": "monsters_hidef"}
FRAME_NAMES = {0: "IDLE1", 1: "IDLE2", 2: "HAPPY", 3: "ANGRY", 4: "TRAIN1", 5: "TRAIN2", 6: "ATK1",
               7: "ATK2", 8: "EAT1", 9: "EAT2", 10: "NOPE", 11: "NAP1", 12: "NAP2", 13: "SICK",
               14: "LOSE", 15: "SPECIAL"}

_listing = {}


def listing(folder):
    """{exact name: kind} and {lower name: exact name} of a sprite library folder."""
    if folder not in _listing:
        exact, lower = {}, {}
        if os.path.isdir(folder):
            for n in os.listdir(folder):
                exact[n] = "dir" if os.path.isdir(os.path.join(folder, n)) else "file"
                lower.setdefault(n.lower(), n)
        _listing[folder] = (exact, lower)
    return _listing[folder]


def frames_of(path, kind):
    out = set()
    if kind == "dir":
        for n in os.listdir(path):
            m = re.fullmatch(r"(\d+)\.png", n, re.I)
            if m:
                out.add(int(m.group(1)))
        return out
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                m = re.fullmatch(r"(\d+)\.png", os.path.basename(n), re.I)
                if m:
                    out.add(int(m.group(1)))
    except zipfile.BadZipFile:
        pass
    return out


def resolve(fmt, module_dir, name):
    """(origin, frames, case_hits) of the set the game would draw, or (None, None, case_hits)."""
    folder = FOLDERS[fmt]
    case_hits = []
    for base, origin in ((os.path.join(module_dir, folder), "module"), (os.path.join(ASSETS, folder), "assets")):
        exact, lower = listing(base)
        for candidate, kind in ((name, "dir"), (name + ".zip", "file")):
            if exact.get(candidate) == kind:
                got = frames_of(os.path.join(base, candidate), kind)
                if got:
                    return origin + (" zip" if kind == "file" else " folder"), got, None
            elif candidate.lower() in lower and candidate not in exact:
                case_hits.append(f"{origin}/{folder}/{lower[candidate.lower()]}")
    return None, None, case_hits


def sprite_name(pet, fmt_str):
    return (fmt_str or "$_dmc").replace("$", pet).replace(":", "_")


def fmt_frames(frames):
    return ", ".join(f"{f} {FRAME_NAMES.get(f, '')}".strip() for f in frames)
