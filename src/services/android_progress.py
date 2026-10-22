"""Android-only save/lifecycle adapter for offline care and native reminders.

Existing save rotation and GamePet.update are unchanged. Metadata is optional
in older saves. JNI failures never prevent pet recovery or foreground play.
"""
import copy
import json
import math
import random
import threading
import time
import uuid
from datetime import datetime

from core import game_globals as game, runtime_globals as runtime, constants
from services.android_offline import OfflineWorld, event_from_data

VERSION = 1
FORECAST_DAYS = 7
_checkpoint = None
_prepared = None
_recovering = False
_background = False
_native = None
_forecast_generation = None
_forecast_lock = threading.Lock()
_lifecycle_registered = False
_callbacks_ref = None
_last_error = ''
_intent_callback = None
_game_instance = None
_needs_scene_refresh = False
_outbox_busy = False
_opened_at = time.time()


def native():
    global _native, _last_error
    if not runtime.IS_ANDROID:
        return None
    if _native is None:
        try:
            from jnius import autoclass
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            _native = autoclass('org.omnipet.offline.PetNotifications')
            _native.initialize(activity)
        except Exception as exc:
            _last_error = str(exc)
            return None
    return _native


def clock_record():
    wall = time.time()
    try:
        n = native()
        return {'wall': wall, 'elapsed': n.elapsedSeconds(), 'boot': str(n.bootId())} if n else {'wall': wall}
    except Exception:
        return {'wall': wall}


def elapsed_since(previous, current):
    """Suspend-inclusive clock within a boot; nonnegative UTC across reboots."""
    if previous.get('boot') and previous.get('boot') == current.get('boot'):
        elapsed = current.get('elapsed', 0) - previous.get('elapsed', 0)
    else:
        elapsed = current['wall'] - previous['wall']
    return max(0.0, elapsed) if math.isfinite(elapsed) else 0.0


def snapshot(meta, monotonic_time=None, restored=False):
    from models.game_digidex import load_digidex
    mono = time.monotonic() if monotonic_time is None else monotonic_time
    at = meta['clock']['wall']
    data = {k: copy.deepcopy(getattr(game, k)) for k in (
        'unlocks', 'traited', 'generations', 'gcell_fragments', 'quests', 'friends',
        'friend_event_pending', 'xai', 'xai_date', 'event_time', 'event')}
    data.update(at=at, generation=meta['generation'], rng=meta['rng'],
                zone=meta.get('zone'), utc_offset=meta.get('utc_offset', 0),
                event_until=at + meta.get('event_remaining', 60),
                pets=[p.android_offline_snapshot(at, mono, restored) for p in game.pet_list],
                poop_list=[copy.deepcopy(p.__dict__) for p in game.poop_list],
                # The Settings override lives on the configuration.
                sleep_time=getattr(getattr(game, 'configuration', None), 'sleep_time', None),
                wake_time=getattr(getattr(game, 'configuration', None), 'wake_time', None),
                digidex=copy.deepcopy(meta.get('digidex_pending', load_digidex())))
    return data


def before_save():
    """Called inside the existing save path; no disk writes or notifications."""
    global _prepared
    if not runtime.IS_ANDROID or _recovering:
        return getattr(game, 'android_offline', None)
    old = getattr(game, 'android_offline', None) or {}
    meta = {'version': VERSION, 'profile': game.get_save_dir(), 'clock': clock_record(),
            'generation': uuid.uuid4().hex, 'rng': random.Random().getstate(),
            'last_opened': old.get('last_opened') or _opened_at,
            'last_closed': time.time() if _background else old.get('last_closed'),
            'outbox': copy.deepcopy(old.get('outbox', [])),
            'consumed': list(old.get('consumed', []))[-64:]}
    try:
        n = native()
        if n:
            meta['zone'] = str(n.timezoneId())
            meta['utc_offset'] = n.utcOffsetSeconds()
    except Exception:
        pass
    if old.get('digidex_pending') is not None:
        meta['digidex_pending'] = copy.deepcopy(old['digidex_pending'])
    scene = getattr(_game_instance, 'scene', None)
    if game.event is not None and getattr(scene, 'event_stage', 0) == 1:
        meta['event_remaining'] = max(0, 60 - scene.event_alert_timeout / game.configuration.frame_rate)
    if (scene is not None and getattr(scene, 'event_stage', 0) == 2
            and game.event is not None and game.event.type.value == 1
            and getattr(scene, 'event_gift_timer', 0) <= 4 * game.configuration.frame_rate):
        meta['accepted_gift'] = {'module': game.event.module, 'item': game.event.item,
                                 'quantity': game.event.item_quantity}
    _prepared = snapshot(meta)
    _prepared['accepted_gift'] = copy.deepcopy(meta.get('accepted_gift'))
    game.android_offline = meta
    return meta


def after_save(meta):
    """Publish only a checkpoint whose existing save operation succeeded."""
    global _checkpoint, _forecast_generation
    if not runtime.IS_ANDROID or _recovering or not meta or not _prepared:
        return
    if _prepared['generation'] != meta['generation']:
        return
    _checkpoint = copy.deepcopy(_prepared)
    _forecast_generation = meta['generation']
    n = native()
    if n:
        n.expectGeneration(meta['generation'])
    # The snapshot is isolated. A new save supersedes a still-running forecast.
    captured = copy.deepcopy(_checkpoint)
    modules = dict(runtime.game_modules)
    profile = meta['profile']
    def forecast():
        global _last_error
        with _forecast_lock:
            if captured['generation'] != _forecast_generation:
                return
            try:
                world = OfflineWorld(captured, modules).advance(captured['at'] + FORECAST_DAYS * 86400)
                plan = {'generation': captured['generation'], 'profile': profile,
                        'until': int(world.cursor * 1000), 'entries': world.notices}
                if captured['generation'] == _forecast_generation:
                    n = native()
                    if n:
                        n.publish(json.dumps(plan))
            except Exception as exc:
                _last_error = str(exc)
                print(f'[Offline] Notification forecast failed: {exc}')
    threading.Thread(target=forecast, name='pet-notification-forecast', daemon=True).start()
    flush_effects(meta)


def on_load():
    """Android only, after the existing loader restored all pets and settings."""
    global _checkpoint
    if not runtime.IS_ANDROID:
        return
    meta = getattr(game, 'android_offline', None)
    if not isinstance(meta, dict) or meta.get('version') != VERSION or meta.get('profile') != game.get_save_dir():
        # No speculative age penalty for legacy saves or a different profile.
        game.android_offline = None
        _checkpoint = None
        n = native()
        if n:
            n.cancelPlan()
            n.consumeClaim()
        return
    # The pets stand as the save left them; loading the rest is not time away.
    _checkpoint = snapshot(meta, restored=True)
    _checkpoint['accepted_gift'] = copy.deepcopy(meta.get('accepted_gift'))
    recover()


def enter_background():
    global _background
    if _background:
        return
    _background = True
    n = native()
    if n:
        n.setForeground(False)
    game.save()


def enter_foreground():
    global _background
    n = native()
    if n:
        n.setForeground(True)
    if _background:
        recover()
    _background = False


def recover_suspension(seconds):
    """Android fallback when SDL reports a gap without a pause callback.

    Use the live party at the last frame, preserving actions since autosave.
    Do not reload an older checkpoint or treat ordinary window events as time
    away. The caller supplies the observed SDL elapsed gap.
    """
    global _checkpoint
    if seconds <= 0 or not math.isfinite(seconds) or not game.pet_list:
        return
    current = clock_record()
    meta = copy.deepcopy(getattr(game, 'android_offline', None) or {})
    meta.update(version=VERSION, profile=game.get_save_dir(),
                generation=uuid.uuid4().hex, rng=random.Random().getstate())
    origin = dict(current, wall=current['wall'] - seconds)
    if 'elapsed' in origin:
        origin['elapsed'] -= seconds
    meta['clock'] = origin
    game.android_offline = meta
    _checkpoint = snapshot(meta, time.monotonic() - seconds)
    recover()


def recover():
    global _recovering, _checkpoint, _forecast_generation, _last_error, _needs_scene_refresh
    meta = getattr(game, 'android_offline', None)
    if _recovering or not _checkpoint or not meta or meta.get('profile') != game.get_save_dir():
        return False
    n = native()
    claim = None
    if n:
        n.setForeground(True)
        try:
            claim = json.loads(str(n.peekClaim()))
        except Exception:
            pass
        n.cancelPlan()
    _forecast_generation = None
    # One instant on both clocks: the result is placed at the moment it was
    # computed for, not after the time computing it took.
    reached, reached_mono = clock_record(), time.monotonic()
    target = _checkpoint['at'] + elapsed_since(meta['clock'], reached)
    _recovering = True
    try:
        world = OfflineWorld(_checkpoint, dict(runtime.game_modules)).advance(target)
        apply_world(world, reached_mono)
        gift = _checkpoint.get('accepted_gift')
        if gift:
            from utils.inventory_utils import get_item_by_name, add_to_inventory
            item = get_item_by_name(gift['module'], gift['item'])
            add_to_inventory(item.id if item else gift['item'], gift['quantity'])
            meta.pop('accepted_gift', None)
        meta['last_opened'] = time.time()
        meta['event_remaining'] = max(0, world.event_until - target) if game.event is not None else 60
        if valid_claim(claim, meta):
            candidate = event_from_data(claim['event'])
            if candidate.module in runtime.game_modules and any(
                p.state not in ('dead', 'nap') and (candidate.global_event or p.module == candidate.module)
                and (candidate.type.value != 0 or p.can_battle()) for p in game.pet_list
            ):
                game.event = candidate
                meta['event_remaining'] = 60
            meta.setdefault('consumed', []).append(claim['id'])
        # Publish updated care state using exactly the existing save mechanism.
        # Keep calculated progress in memory if saving fails; never replay it.
        meta['clock'] = clock_record()
        meta['rng'] = world.rng.getstate()
        game.android_offline = meta
        _checkpoint = snapshot(meta)
        success = game.save()
        if success and n:
            n.consumeClaim()
        if success:
            flush_effects(meta)
        _needs_scene_refresh = True
        return True
    except Exception as exc:
        _last_error = str(exc)
        print(f'[Offline] Recovery failed: {exc}')
        raise
    finally:
        _recovering = False


def valid_claim(claim, meta):
    return (isinstance(claim, dict) and isinstance(claim.get('event'), dict)
            and claim.get('profile') == meta.get('profile')
            and claim.get('generation') == meta.get('generation')
            and claim.get('id') not in meta.get('consumed', [])
            and claim.get('posted', 0) <= claim.get('entered', -1) <= claim.get('expires', -2))


def _walk_range(pet):
    return getattr(pet, 'x_range', None) or (0, runtime.SCREEN_WIDTH - runtime.PET_WIDTH)


def apply_world(world, monotonic_time=None):
    from models.game_poop import GamePoop
    old = {p.android_id: p for p in game.pet_list}
    mono = time.monotonic() if monotonic_time is None else monotonic_time
    # Pets wander while the app is open, so after time away they are shown
    # somewhere else and each poop where it was dropped, not in one heap at
    # the closing position. Presentation only: the cosmetic RNG idle movement
    # uses, never the saved gameplay one the forecast shares.
    moved = world.cursor - world.started >= 60
    result = []
    for computed in world.pet_list:
        live = old[computed.android_id]
        live.android_apply_offline(computed.export(), world.cursor, mono)
        if moved and live.stage > 0 and live.state not in ('nap', 'dying', 'dead'):
            low, high = _walk_range(live)
            live.x = random.randint(int(low), int(high))
            live.subpixel_x = float(live.x)
            live.direction = random.choice((-1, 1))
        result.append(live)
    for pet in game.pet_list:
        if pet not in result:
            runtime.pet_sprites.pop(pet, None)
    game.pet_list = result
    game.poop_list = []
    spot = 0
    for data in world.poop_list:
        data = dict(data)
        if 'owner' in data:
            owner = old.get(data.pop('owner'))
            scale = runtime.UI_SCALE
            count = data.pop('count', 1)
            index = data.pop('index', 0)
            if index == 0:  # one spot per poop event; a double or triple stays together
                low, high = _walk_range(owner)
                spot = random.uniform(low, high) if moved else getattr(owner, 'x', 0)
            offset = (index - (count - 1) / 2) * (24 if count == 2 else 18) * scale
            data['x'] = (spot + 12 * scale
                         + constants.FRAME_SIZE / 2 + offset)
            data['y'] = (getattr(owner, 'y', 0) + runtime.PET_HEIGHT
                         - (48 if data.get('jumbo') else 24) * scale)
        poop = GamePoop(data.get('x', 0), data.get('y', 0),
                        jumbo=data.get('jumbo', False),
                        use_dot_sprite=data.get('use_dot_sprite', False),
                        use_hd_sprite=data.get('use_hd_sprite', False))
        poop.__dict__.update(data)
        poop.patch()
        game.poop_list.append(poop)
    for key in ('unlocks', 'traited', 'generations', 'gcell_fragments', 'quests', 'friend_event_pending',
                'xai', 'xai_date', 'event_time'):
        setattr(game, key, copy.deepcopy(getattr(world, key)))
    # Offline arrivals are represented by native claims, never replayed in bulk.
    game.event = world.event if world.event is world.initial_event else None
    if game.event is not None:
        game.event.android_remaining_seconds = max(0, world.event_until - world.cursor)
        game.event.android_silent_arrival = True
    meta = game.android_offline
    # Commit the Digidex/outbox intent inside the existing save first. If the
    # app dies before the separate Digidex file is written, the next load retries.
    meta['digidex_pending'] = copy.deepcopy(world.digidex)
    outbox = meta.setdefault('outbox', [])
    for effect in world.effects:
        if effect['kind'] == 'evolution':
            outbox.append(('evolution', 'evolution:offline:' + effect['id']))
        elif effect['kind'] == 'discovery':
            outbox.append(('new_pet', f"new_pet:{effect['module']}:{effect['name']}:{effect['version']}"))
        elif effect['kind'] == 'unlock':
            outbox.append(('unlock', f"unlock:{effect['module']}:{effect['type']}:{effect['name']}"))
            if effect.get('card'):
                from utils.card_utils import add_card_copy
                add_card_copy(effect['module'], effect['card'], shiny=True)
    runtime.evolution_pet = None
    runtime.selected_pets = []
    runtime.game_pet_eating = {}
    runtime.friend_celebration = None
    if len(old) != len(result):
        from utils.pet_utils import refresh_pet_sizes
        refresh_pet_sizes()


def flush_effects(meta):
    """Android-only reward outbox: saved before dispatch, stable server keys."""
    global _outbox_busy
    if meta.get('digidex_pending') is not None:
        from models.game_digidex import save_digidex
        save_digidex(meta['digidex_pending'])
        meta.pop('digidex_pending', None)
    if not game.is_progress_mode():
        meta['outbox'] = []
        return
    if _outbox_busy or not meta.get('outbox'):
        return
    from services.omninet_service import omninet_service
    if not omninet_service.is_logged_in():
        return
    profile = meta['profile']
    entries = list(dict.fromkeys(tuple(e) for e in meta['outbox']))
    _outbox_busy = True
    def send():
        global _outbox_busy
        try:
            for kind, key in entries:
                if game.get_save_dir() != profile:
                    break
                success, response = omninet_service._make_request('POST', '/api/v1/rewards/claim',
                    {'event_type': kind, 'idempotency_key': key})
                # The server answers a key it credited before (the app died
                # before saving the acknowledgement) with 400 "Already
                # claimed": that is an acknowledgement, not a failure to retry
                # at every checkpoint forever.
                already = (not success and isinstance(response, str)
                           and 'already claimed' in response.lower())
                if not success and not already:
                    continue
                current = getattr(game, 'android_offline', None)
                if not current or current.get('profile') != profile or game.get_save_dir() != profile:
                    break
                current['outbox'] = [e for e in current.get('outbox', []) if tuple(e) != (kind, key)]
                if isinstance(response, dict):
                    for name in ('total_coins', 'total', 'new_balance', 'coins'):
                        if response.get(name) is not None:
                            game.coins = int(response[name])
                            break
                # The next normal checkpoint persists acknowledgement. A crash
                # simply retries the same key, which the server deduplicates.
        except Exception as exc:
            print(f'[Offline] Reward retry deferred: {exc}')
        finally:
            _outbox_busy = False
    threading.Thread(target=send, name='offline-rewards', daemon=True).start()


def refresh_scene(game_instance):
    """Warm resume: discard obsolete presentation before the first frame."""
    global _game_instance, _needs_scene_refresh
    _game_instance = game_instance
    # Cold start must still run normal setup/account/module checks in SceneBoot.
    if _needs_scene_refresh and type(game_instance.scene).__name__ != 'SceneBoot':
        from utils.scene_utils import change_scene
        change_scene('game' if game.pet_list else 'egg')
        # VirtualPetGame.change_scene keeps a scene of the same class. A kept
        # main screen holds the pre-pause event alert stage: an alert that
        # expired offline would leave it at stage 1, which stops the event
        # clock, and a still-valid one would ignore its remaining window.
        game_instance.scene = None
        game_instance.change_scene()
    _needs_scene_refresh = False


def request_notification_permission():
    if not runtime.IS_ANDROID:
        return
    n = native()
    if n:
        n.requestPermission()


def notification_status():
    n = native()
    return str(n.status()) if n else 'Unavailable'


def open_notification_settings():
    n = native()
    if n:
        n.openSettings()


def install_intent_hook():
    global _intent_callback
    n = native()
    if n is None:
        return
    from jnius import autoclass
    activity = autoclass('org.kivy.android.PythonActivity').mActivity
    n.captureIntent(activity.getIntent())
    if _intent_callback is None:
        from android import activity as events
        def on_intent(intent):
            # Native capture is brief and timestamps entry before Python loads.
            n.captureIntent(intent)
        _intent_callback = on_intent
        events.bind(on_new_intent=_intent_callback)


def install_lifecycle_hooks(on_pause=None, on_resume=None):
    """Register an Application.ActivityLifecycleCallbacks listener via JNI.

    SDL2's APP_DIDENTERBACKGROUND event isn't surfaced by pygame on
    every p4a build (notably the MIUI/Xiaomi case observed in the wild
    where pygame never delivers the lifecycle event).  This hooks
    Android's own per-activity callbacks, which fire on *every* Android
    version regardless of SDL routing.

    The provided callbacks run on Android's UI thread, and getting there
    from Java costs a ``PyGILState_Ensure()`` — so they must do nothing
    but set a flag the pygame loop consumes.  A callback that saves,
    calls JNI, or imports anything holds the UI thread for as long as it
    takes to get the GIL, and if the pygame thread is blocked inside
    SDL's Android event pump (see the header of ``main_android.py``) it
    never gets it: ``onActivityResumed`` then deadlocks the very thread
    that was about to deliver ``nativeResume``.

    No-op on non-Android, on failure, or on a second call (registration
    is idempotent for the lifetime of the process).
    """
    global _lifecycle_registered
    if _lifecycle_registered or not runtime.IS_ANDROID:
        return False

    try:
        from jnius import autoclass, PythonJavaClass, java_method  # type: ignore
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        mActivity = PythonActivity.mActivity
        Application = mActivity.getApplication()

        class _Callbacks(PythonJavaClass):
            __javainterfaces__ = [
                "android/app/Application$ActivityLifecycleCallbacks"
            ]
            __javacontext__ = "app"

            @java_method("(Landroid/app/Activity;Landroid/os/Bundle;)V")
            def onActivityCreated(self, activity, savedInstanceState):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityStarted(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityResumed(self, activity):
                try:
                    if on_resume:
                        on_resume()
                except Exception as cb_exc:
                    print(f"[Offline] on_resume callback error: {cb_exc}")

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPaused(self, activity):
                try:
                    if on_pause:
                        on_pause()
                except Exception as cb_exc:
                    print(f"[Offline] on_pause callback error: {cb_exc}")

            @java_method("(Landroid/app/Activity;)V")
            def onActivityStopped(self, activity):
                pass

            @java_method("(Landroid/app/Activity;Landroid/os/Bundle;)V")
            def onActivitySaveInstanceState(self, activity, outState):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityDestroyed(self, activity):
                pass

            # --- API 29+ default methods ---
            # pyjnius raises NotImplementedError for each unimplemented default
            # method in the interface, which can prevent the preceding real
            # callbacks (onActivityPaused etc.) from executing on some devices.
            @java_method("(Landroid/app/Activity;Landroid/os/Bundle;)V")
            def onActivityPreCreated(self, activity, savedInstanceState):
                pass

            @java_method("(Landroid/app/Activity;Landroid/os/Bundle;)V")
            def onActivityPostCreated(self, activity, savedInstanceState):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPreStarted(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPostStarted(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPreResumed(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPostResumed(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPrePaused(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPostPaused(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPreStopped(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPostStopped(self, activity):
                pass

            @java_method("(Landroid/app/Activity;Landroid/os/Bundle;)V")
            def onActivityPreSaveInstanceState(self, activity, outState):
                pass

            @java_method("(Landroid/app/Activity;Landroid/os/Bundle;)V")
            def onActivityPostSaveInstanceState(self, activity, outState):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPreDestroyed(self, activity):
                pass

            @java_method("(Landroid/app/Activity;)V")
            def onActivityPostDestroyed(self, activity):
                pass

        # Hold a reference so the JVM doesn't GC the listener.
        global _callbacks_ref
        _callbacks_ref = _Callbacks()
        Application.registerActivityLifecycleCallbacks(_callbacks_ref)
        _lifecycle_registered = True
        print("[Offline] ActivityLifecycleCallbacks installed")
        return True
    except Exception as exc:
        print(f"[Offline] install_lifecycle_hooks failed: {exc}")
        return False
