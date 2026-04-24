"""FC Universitatea Cluj 2024/25 first-team squad (best-effort, public info).

Used as a candidate list for AI name-tagging of playerIds.
Also contains hardcoded overrides keyed by Wyscout playerId for players we've
confirmed manually.
"""

CLUJ_SQUAD_2024_25 = [
    # Goalkeepers
    {"name": "Ştefan Târnovanu", "position": "GK"},
    {"name": "Rareş Fortuna", "position": "GK"},
    {"name": "Andrei Gorcea", "position": "GK"},
    # Defenders
    {"name": "Andrei Murg", "position": "CB"},
    {"name": "Vlad Muşat", "position": "CB"},
    {"name": "Cristian Manea", "position": "RB"},
    {"name": "Mihai Bordeianu", "position": "CB/DM"},
    {"name": "Alexandru Chipciu", "position": "LB/LW"},
    {"name": "Andre Ferreira", "position": "CB"},
    {"name": "Aboubakary Koita", "position": "RB"},
    {"name": "Mattia Masini", "position": "LB"},
    # Midfielders
    {"name": "Dan Nistor", "position": "AM"},
    {"name": "Lukas Zima", "position": "CM"},
    {"name": "Alex Micaș", "position": "CM"},
    {"name": "Damjan Djokovic", "position": "CM"},
    {"name": "Dragoş Iancu", "position": "CM"},
    {"name": "Mamadou Thiam", "position": "AM"},
    {"name": "Brian Brobbey", "position": "CM"},
    # Forwards
    {"name": "Louis Munteanu", "position": "CF"},
    {"name": "Alexandru Mitriță", "position": "LW/AM"},
    {"name": "Daniel Bîrligea", "position": "CF"},
    {"name": "Andrei Gheorghiță", "position": "LW"},
    {"name": "Lindon Emerllahu", "position": "CM"},
    {"name": "Marko Dugandžić", "position": "CF"},
    {"name": "Matija Lješković", "position": "CF"},
    {"name": "Mikanović", "position": "CF"},
    {"name": "Darius Olaru", "position": "AM"},
    {"name": "Cătălin Itu", "position": "CM"},
    {"name": "Andrei Sin", "position": "CF"},
]


# Hardcoded overrides: Wyscout playerId -> name. These win over AI guesses.
# Filled in manually after inspecting ingest output.
MANUAL_OVERRIDES = {
    # Top scorer in DB (18 goals, 11.83 xg) — most likely Louis Munteanu (but could be another attacker).
    # Leave empty until we verify via public Wyscout platform.
}
