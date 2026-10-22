# -*- coding: utf-8 -*-
"""The seasons the simulation plays, one dict each.

``players`` is how many take part (game instances included), ``days`` the
number of compressed attack days of ``day_minutes`` each (the season lasts
days x day_minutes), ``restrictions`` / ``config`` / ``reward_multiplier``
go to the server as a season's own. ``probes`` are the abuses some players
try during registration (each must be refused).
"""

DEFAULT_PROBES = ["edited_stats", "unpublished", "veteran", "wrong_size", "duplicate",
                  "second_team"]

SCENARIOS = [
    {"name": "Sim Open Cup", "players": 8, "days": 3,
     "restrictions": None, "config": {}},
    {"name": "Sim Child League", "players": 6, "days": 2,
     "restrictions": {"allowed_stages": [3]}, "config": {"team_size": 3}},
    {"name": "Sim Solo Duel", "players": 10, "days": 3,
     "restrictions": None, "config": {"team_size": 1, "charge": "random", "attacks_per_day": 6}},
    {"name": "Sim Vaccine Pairs", "players": 5, "days": 3,
     "restrictions": {"allowed_attributes": ["Vaccine"]}, "config": {"team_size": 2}},
    {"name": "Sim Classic Modules", "players": 7, "days": 3,
     "restrictions": {"allowed_modules": ["DMC", "DMX", "PENC", "DM20"]},
     "config": {"attacks_per_day": 5}},
    {"name": "Sim Perfect Rush", "players": 9, "days": 2,
     "restrictions": {"allowed_stages": [5]}, "config": {}, "reward_multiplier": 2.0},
    {"name": "Sim Virus-Data Brawl", "players": 6, "days": 3,
     "restrictions": {"allowed_attributes": ["Virus", "Data"]},
     "config": {"charge": 3, "win_score": 30, "loss_score": -5, "draw_score": 10}},
    {"name": "Sim Ultimate Showdown", "players": 5, "days": 2,
     "restrictions": {"allowed_stages": [6]}, "config": {"charge": 0}},
    {"name": "Sim Bracelet Cup", "players": 8, "days": 3,
     "restrictions": {"allowed_modules": ["VB", "VBE", "VH"]}, "config": {}},
    {"name": "Sim Grand Prix", "players": 10, "days": 4,
     "restrictions": None,
     "config": {"attacks_per_day": 5, "rank_prizes": [100, 60, 40, 20, 10]}},
    {"name": "Sim Adult Trios", "players": 7, "days": 3,
     "restrictions": {"allowed_stages": [4]},
     "config": {"team_size": 3, "participation_coins": 2}},
    {"name": "Sim Twos and Threes", "players": 6, "days": 2,
     "restrictions": None, "config": {"min_team_size": 2, "attacks_per_day": 8}},
]
