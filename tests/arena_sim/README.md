# Arena season simulation

Crawlers that play whole Arena seasons against a real Omninet server, the
way players would, and check every step. Not part of `run_tests.py`: they
need a running server and a database, and a full run takes a couple of
hours.

| File | Does |
|---|---|
| `run_seasons.py` | The orchestrator: starts a local Omninet, opens each season of `scenarios.py`, lets 5-10 players register and fight, lets the season clock close it, checks results, prizes, claims and records, writes the report |
| `players.py` | API players: real `GamePet`s, the game's own eligibility (`_pet_passes`), upload (`_pet_to_upload`) and Omninet client; they raise and evolve pets between seasons and try abuses the server must refuse |
| `game_player.py` | A real headless game instance (one process each, `tests/support/harness.Env`), driven through the arena screens with taps: team creation, FIND BATTLE with the replay played to the end, history and defence replays, ranks, rules, season results |
| `scenarios.py` | The seasons: rules, team sizes, charge, scoring, prizes, multiplier |
| `simlib.py` | Server process, dev tools client, per-player game clients |
| `summarize.py` | Totals of a run (seasons, battles, replays, probes, failed checks) |

## Running

```powershell
# Python 3.11+ with Omninet's requirements, for the server
$py = "C:\path\to\omninet-venv\Scripts\python.exe"
# a runtime for the server (published modules; IC is bundled on purpose to
# prove an unpublished module is refused)
python utilities/claude/build_arena_runtime.py --modules DM20 DMC DMGZ DMH DMOG DMRV DMX DMXW PEN20 PENC PENOG PENZ VB VBE VH IC --to E:/Omninet/storage/arena_local/updates
python -B tests/arena_sim/run_seasons.py --server-python $py                 # every scenario
python -B tests/arena_sim/run_seasons.py --server-python $py --seasons 1 --quick --api-players 4 --game-players 1
```

The server runs from `OMNINET_DIR` (default `E:/Omninet`) on port 8765 with
its `.env` database (the dev database), `ENVIRONMENT=dev`, shop sync and
automatic seasons off, the dev token `sim-dev-token` and its own arena store
`storage/arena_local`. Seasons use compressed days (`--day-minutes`, the
season config's `day_minutes`): the daily attack allowance resets every few
minutes, so a week-long season plays in a quarter of an hour.

Accounts are `simplayer1..N` (API) and `simgame1..3` (game instances),
created through `/dev/arena/accounts` with a fresh device each run.

### Against a deployed server

```powershell
python -B tests/arena_sim/run_seasons.py --url https://dev.omnipet.app.br --admin-key-file <file with an admin device key>
```

Nothing is started or stopped locally; game instances may reach that host. The
deployed dev server has no `ARENA_DEV_TOKEN`, so its dev tools take an admin
`X-Device-Key`: the test account `simadmin` (user type Admin, created
2026-10-17 for this; delete it when no longer wanted). The runtime the seasons
fight on is whatever the server has installed: upload a build with
`POST /admin/arena/updates/omnipet` and `POST /admin/arena/updates/sync-published`
first; the first season the simulation opens installs them.

## What is checked

- Registration: team size per season, restrictions, published modules
  only, an edited species value refused, a Digimon that already fought in
  its form refused until it evolves, the same Digimon twice, a second team.
- Every battle: the stored log replays to the same result in the game's
  engine (same seed), opens from both seats, scores follow the season, the
  allowance counts down and is enforced.
- Matchmaking: each attack goes to a team the attacker met least that day;
  defences spread over the teams (min/max per season in the report).
- Game instances: the picker explains refused pets and warns about the
  lock, the team goes into the freezer locked, every replay reaches its
  result on the server's HP and verdict and returns to the hub (or to the
  history), the hub shows the result line, ranks and rules.
- Season close (by the season clock): ranks 1..N with teams that fought
  first, rank prizes (times the multiplier), the podium in
  `season_winners`, coins = participation + prize, one claim only, every
  pet gets the team's record, the game puts it on the pets and frees them.

The report is `tmp/arena_sim/run-<time>/report.md` (`report.json` holds
everything; `shots/` has screenshots of the game instances; `server.log`).

## Sharing the dev database

The deployed dev server runs its own season clock on the same database. If
it closes a simulation season first (it ticks once a minute), that season's
prizes follow its older code; the report notes "closed by another server's
clock" and skips the prize checks for it. The simulation closes its seasons
within a second of their end, so this is rare.
