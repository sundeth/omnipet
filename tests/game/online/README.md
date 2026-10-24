# Online tests (fake Omninet)

Tests of everything that talks to Omninet: the login scene, the connect menu,
the shop, the arena and the reward outbox. They run against
`tests/support/fake_omninet.py`, an in-memory server on `127.0.0.1` with the
request and response shapes of the real one (`E:/Omninet/omninet/routes/`).
Nothing here contacts `omnipet.app.br`, `dev.omnipet.app.br`, Discord or
wificom: the harness is booted with `Env(..., network="local")`, which refuses
every connection that is not to this machine.

| File | Covers |
|---|---|
| `tests/unit/online/test_omninet_client.py` | `OmninetService` call by call: linking, register/login codes, auto-login, logout, purchases, every call under every fault, rewards, the Android reward outbox (AND-08) |
| `test_online_login.py` | `SceneLogin` phases by tap, logout from Config, a second device on the same account (ONL-02) |
| `test_online_shop.py` | Shop views: item, module (download, install, load), background (download, Settings), Free Mode download, second device (ONL-01/02/04) |
| `test_online_shop_delivery.py` | What a purchase delivers with Omninet's real data shapes: a shop item a module also defines (counted once, any Digimon), its icon, a background whose download has no picture, the module price after the free first one, a module install held by a scanner (ONL-01) |
| `test_online_arena.py` | Arena hub, team creation and the freezer lock, Find Battle, history, replays and their return, season results and reward (ONL-03, ARN-05, ARN-07) |
| `test_online_failures.py` | Down, slow, broken or half-done requests in every view (ARN-08, ONL failure paths, BLD-04) |
| `online_ui.py` | Helpers for these files (not a test): find and tap buttons, type into fields, tap list rows and pet cells, wait for workers |

Bugs these tests found are marked `@unittest.expectedFailure` and listed in
`tests/findings/online.md`.

## Starting the fake server for a menu-crawl fixture

```python
from harness import Env
from fake_omninet import FakeOmninet, isolate_client, login_service, module_zip, \
    redirect_relative_save, wait_for

env = Env("240x240", network="local")          # 1. boot first: it imports the scenes
fake = FakeOmninet(arena_modules=["DMC", "PENC", "IC", "VB"]).start()   # 2. a free port
iso = isolate_client(env, fake)                 # 3. point the game at it
svc = iso.__enter__()

# 4. what the online screens need to show something
acc = fake.add_account("Crawler", coins=500)
fake.add_module("DMOG", module_zip("modules/DMOG"), version="1.0.3")
fake.add_item("Super Meat", price=10, json_data={"status": "hunger", "amount": 1})
fake.add_cosmetic("Starry Night", price=20)
season = fake.start_season("Crawl Season")
fake.add_opponent_team("Rival", seed=7, modules=["DMC"])

def online_fixture():                           # 5. after every env.reset()
    login_service(svc, fake, acc)               #    reset() wipes the save folder,
    env.gg.game_mode = env.gg.GAME_MODE_PROGRESS  #  where the device key lives,
    env.gg.player_id = acc["id"]                #    and restores game_mode
    env.gg.save_game_mode_preference()
    env.gg.coins = fake.account(acc)["coins"]

...                                             # crawl
iso.__exit__(None, None, None)                  # 6. restore, then stop
fake.stop()
```

`isolate_client(env, fake_or_url)` does, for as long as it is entered:

- sets `OMNIPET_OMNINET_URL` (what `OmninetService` uses) to the fake;
- points `constants.OMNINET_LOCAL_URL` and `OMNINET_MAIN_URL` at it too: the
  connect menu probes those directly instead of asking the service (the known
  bug **BLD-04**, `main_menu_view.py:643` and `:923`); without the patch the
  crawl would look up `dev.omnipet.app.br`;
- sets `constants.DISCORD_BOT_URL` to the fake (it answers 404), so a linked
  Discord account never reaches `localhost:5000`;
- moves the service's credential file into `env.save_root` (it is computed at
  import as the cwd-relative `save/omninet_device.json`, the repository's own
  save folder: the harness does not redirect it);
- sends module installs (shop download, owned-module sync) to a temp folder
  (`module_utils.get_modules_dir` and the shop view's copy). After an install
  `load_modules()` reads only that folder, so `rg.game_modules` holds just the
  downloaded module until the next `env.reset()`;
- switches the sprite sync off (it would write into `assets/`) and clears the
  shop image cache.

Useful states for crawl fixtures:

| Fixture | Set-up |
|---|---|
| online, logged out (Free Mode) | `isolate_client(env, fake)` only; `game_mode` Free |
| online, logged in | `online_fixture()` above |
| online with a team | then `svc.create_team(engine.random_team(fake.arena_catalog, 3, modules=["DMC"]))`, or tap through CREATE TEAM |
| season results pending | a team, `fake.fight(team, rival)`, `fake.end_season()` |
| Omninet down | `isolate_client(env, FakeOmninet.dead_url())` (on Windows a refused local connect takes about 2 s, so every probe waits that long) |
| Omninet erroring | `fake.fault("/api/v1/shop", "500")`, `"malformed"`, `"reset"`, `"slow"` (with `delay=`), ... |

Things a crawler must allow for:

- **Worker threads change the UI.** Shop and arena views load in threads that
  rebuild components and even call `change_view` themselves. Wait for the
  view's own flag (`state == "list"`, `_loading is False`, `_downloading is
  False`, `scene._async_result`) with `wait_for()` before stepping frames,
  otherwise the main thread draws while the worker mutates the component list.
- **The cosmetics download writes to the cwd-relative `save/`** (the
  repository's save folder, bug in `tests/findings/online.md`). Wrap a crawl
  that can press a cosmetic's Download in `redirect_relative_save(temp)`.
- **Touch mode keyboard.** In TOUCH/GPIO input mode a focused text field opens
  an on-screen keyboard over the bottom 100 px, where the login forms keep
  their buttons; a tap outside the field closes it (`online_ui.type_into`).
- **The login scene is mandatory** in Progress Mode without an account: it has
  no Back; only "Change to Free Play" leaves it.
- **Replays.** Find Battle and history WATCH switch to `battle_pvp`; a crawler
  can leave with `game.scene.battle_encounter.finish_replay()`, which returns
  to the view that opened it.
- **Shop sprite fetches.** A module logo or background preview that arrives
  late rebuilds the detail view; `online_ui.detail_settled()` waits for them.
