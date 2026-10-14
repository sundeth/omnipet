"""Arena Season battles.

``engine`` is the headless rules engine the Omninet server runs from its own
copy of Omnipet: it rebuilds each uploaded Digimon from the server's module
data plus the player's care status, validates season restrictions and plays
the battle. ``replay`` holds the pure helpers the game uses to show a stored
battle from either team's side. Neither may import pygame.
"""
