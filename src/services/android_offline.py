"""Android-only offline calculation. No live globals, sprites, saves or JNI.

Both prediction and recovery run this isolated world; the existing foreground
GamePet.update remains the authority for the minute-rule order. Wall timestamps
are seconds, pet counters are minutes. Only the Android adapter commits results.
"""
import copy
import math
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core import constants, pet_stats
from models.event_clock import EventClock
from services.android_pet_rules import AndroidPetRules
from utils import ailments


class OfflinePet(AndroidPetRules):
    def __init__(self, data, world):
        self.__dict__.update(copy.deepcopy(data))
        # A checkpoint from before the sickness/injury split (GamePet.patch).
        ailments.migrate(self.__dict__)
        self.world = world
        self.removed = False

    def set_state(self, state, force=False):
        if self.state == 'dead' or (self.state == 'dying' and state not in ('dead', 'happy2', 'dying')):
            return
        if self.stage == 0 and state not in ('idle', 'hatch'):
            return
        self.state = state
        if state == 'nap':
            self.sleep_start_time = self.world.now
            # Asleep: the bedtime call is over, as GamePet.set_state has it
            self.care_sleep_mistake_timer = 0
        elif state == 'idle':
            self.sleep_start_time = None

    def load_sprite(self):
        """Android forecast/recovery never load intermediate sprites."""

    _load_burpmon_sprite = load_sprite

    def evolve_to(self, name, version, reward=True):
        module = self.world.get_module(self.module)
        data = module.get_monster(name, version)
        if not data:
            return False
        # An egg's DNA hatches with it; every other evolution clears it.
        if int(getattr(self, 'stage', 0) or 0) != 0:
            self.dna = []
        self.evolution_history = getattr(self, 'evolution_history', []) + [self.name]
        old_stage = int(getattr(self, 'stage', 0) or 0)
        old_vital = getattr(self, 'vital_values', 0)
        self.set_data(dict(data, module=self.module))
        self.reset_variables()
        # GamePet.evolve_to: Vital Values carry from Stage I through III.
        if self.tracks_vital_values():
            carried = pet_stats.carried_vital_values(old_stage, self.stage, old_vital)
            if carried is not None:
                self.vital_values = carried
        self.state = 'idle'
        self.next_minute = self.world.cursor + 60
        self.world.discover(self, reward)
        return True

    def poop(self):
        """Apply one poop event, with no animation and no sound."""
        module = self.world.get_module(self.module)
        chances = list(getattr(module, 'care_poop_chance', [80, 0, 0, 20]))
        chances = (chances + [0] * 4)[:4]
        if sum(chances) <= 0:
            chances = [100, 0, 0, 0]
        roll = self.world.rng.random() * sum(chances)
        kind = 0
        for kind, chance in enumerate(chances):
            roll -= chance
            if roll < 0:
                break
        count = 1 if kind == 3 else kind + 1
        for index in range(count):
            self.world.poop_list.append({
                'owner': self.android_id, 'jumbo': kind == 3,
                'index': index, 'count': count,
                'use_dot_sprite': getattr(self, 'sprite_format', None) == 'Dot',
                'use_hd_sprite': getattr(self, 'sprite_format', None) == 'HD',
                'x': getattr(self, 'x', 0) + index * 12,
                'y': getattr(self, 'y', 0),
            })
        self.unflushed_poops = getattr(self, 'unflushed_poops', 0) + 1
        if self.unflushed_poops % 2 == 0:
            self._apply_reliability_event('reliability_two_poops')
        self.start_poop_timer(module)
        if self.weight > self.weight_floor():
            self.weight -= 1
        self.update_99g_effect()
        self.state = 'idle'
        if getattr(module, 'care_poop_alarm', True):
            self.world.notice(self, 'poop', 'Cleanup needed', f'{self.name} pooped.')

    def check_wake_up(self):
        # A nap an item started (Digi Bedding) ends on its own time, as
        # GamePet.check_wake_up has it.
        nap_until = getattr(self, 'nap_until', None)
        if nap_until is not None:
            if self.state == 'nap' and self.world.now < nap_until:
                return
            self.nap_until = None
            if self.state == 'nap' and not self.should_sleep():
                self.state = 'idle'
                self.sleep_start_time = None
            return
        if self.state != 'nap' or not getattr(self, 'sleep_start_time', None):
            return
        wake = self.world.wake_time
        if wake is None and self.wakes:
            wake = datetime.strptime(self.wakes.strip(), '%H:%M').time()
        if wake is None:
            return
        # Crossing the boundary works even when minute phases are not :00.
        now = self.world.now
        # The clock was set back past the nap's start: the nap starts now, so
        # the next wake time on the clock ends it, as in GamePet.check_wake_up.
        if self.sleep_start_time > now:
            self.sleep_start_time = now
        boundary = datetime.combine(now.date(), wake)
        if boundary <= self.sleep_start_time:
            boundary += timedelta(days=1)
        if now >= boundary:
            slept = (boundary - self.sleep_start_time).total_seconds()
            if slept >= constants.SLEEP_RECOVERY_HOURS * 3600:
                self.dp = self.energy
            self.state = 'idle'
            self.sleep_start_time = None

    def die(self, late=0.0):
        # A death route may take the pet instead (GamePet._die).
        if self.death_evolution():
            return
        self.dying = False
        self.death_cause = ''
        self.death_save_elapsed = 0.0
        self.state = 'dead'
        self.burpmon_active = False
        self._rt_dead_start = self.world.cursor - late

    def update_death_check(self, now=None):
        if self.check_death_conditions() and self.death_save_immunity == 0:
            self.die()
        if self.state == 'dead' and self._rt_dead_start and self.world.cursor - self._rt_dead_start > 300:
            self.removed = True
            self.set_traited_egg()

    def minute(self, minutes=1):
        """Android-only counterpart of GamePet.update's minute section.

        One call is one update() tick of *minutes*: a single minute, or the
        batch the foreground had not applied when the checkpoint was taken.
        """
        self.check_wake_up()
        # GamePet.update: a death save runs on the clock, ahead of the minute.
        if getattr(self, 'dying', False):
            self.update_death_save(minutes * 60)
        today = self.world.now.date()
        if today > self._last_age_date:
            self.age += (today - self._last_age_date).days
            self._last_age_date = today
        self._rt_last_minute += minutes
        minute_number = self._rt_last_minute  # evolution can reset the stored counter
        if self.state != 'dead':
            self.update_reliability(minutes)
            # Time in this form, and the pet's life, run asleep and awake alike.
            self.form_minutes = (getattr(self, 'form_minutes', 0) or 0) + minutes
            self.life_minutes = (getattr(self, 'life_minutes', 0) or 0) + minutes
        # GamePet.update: the hour's Vital Values before the evolution check.
        if minute_number // 60 > (minute_number - minutes) // 60 and self.state not in ('nap', 'dead'):
            self.update_vital_values_gain()
        if self.state not in ('nap', 'dead'):
            self._evol_minutes += minutes
            self.update_evolution()
            self.update_needs(minutes)
            self.update_pooping(minutes)
            self.update_poop_mistakes(minutes)
            self.update_care_mistakes()
            self.update_vital_values_loss()
        elif self.state == 'nap' and getattr(self.world.get_module(self.module), 'count_evolution_while_sleeping', True):
            self._evol_minutes += minutes
            self.update_evolution()
        if self.state != 'nap':
            self.update_death_check()
            if self.death_save_immunity > 0:
                self.death_save_immunity -= 1
        if self.back_to_sleep > 0:
            self.back_to_sleep -= 1
            if not self.back_to_sleep and self.state != 'nap' and self.should_sleep():
                self.set_state('nap')
        # Complete the visual action after all pets' minute rules, as normal
        # play creates the poop on subsequent animation frames.

    def export(self):
        return copy.deepcopy({k: v for k, v in self.__dict__.items()
                              if k not in ('world', 'removed', 'android_pending_minutes')})


class OfflineWorld:
    def __init__(self, snapshot, modules):
        self.modules = modules
        self.cursor = snapshot['at']
        self.started = self.cursor
        self.zone = None
        if snapshot.get('zone'):
            try:
                self.zone = ZoneInfo(snapshot['zone'])
            except (ZoneInfoNotFoundError, ValueError):
                self.zone = timezone(timedelta(seconds=snapshot.get('utc_offset', 0)))
        self.rng = random.Random()
        self.rng.setstate(snapshot['rng'])
        self.generation = snapshot['generation']
        self.pet_list = [OfflinePet(p, self) for p in snapshot['pets']]
        for key in ('poop_list', 'unlocks', 'traited', 'generations', 'gcell_fragments', 'quests',
                    'friends', 'digidex', 'friend_event_pending'):
            setattr(self, key, copy.deepcopy(snapshot.get(
                key, [] if key not in ('unlocks', 'friends', 'generations') else {})))
        self.sleep_time = snapshot.get('sleep_time')
        self.wake_time = snapshot.get('wake_time')
        self.xai = snapshot['xai']
        self.xai_date = snapshot['xai_date']
        self.event_time = snapshot.get('event_time')
        self.event = copy.deepcopy(snapshot.get('event'))
        self.initial_event = self.event
        self.event_until = snapshot.get('event_until', self.cursor + 60)
        self.next_event_minute = snapshot.get('next_event_minute', self.cursor + 60)
        self.effects = []
        self.notices = []
        self.sequence = snapshot.get('sequence', 0)
        self.calls = {p.android_id: bool(p.call_sign()) for p in self.pet_list}
        self.sickness = {p.android_id: ailments.ailing(p) for p in self.pet_list}
        self.deaths = {p.android_id: p.dying for p in self.pet_list}
        self.active_notices = {}

    @property
    def now(self):
        return datetime.fromtimestamp(self.cursor, self.zone).replace(tzinfo=None)

    def get_module(self, name):
        return self.modules[name]

    def log(self, *args):
        pass

    sound = log

    def is_unlocked(self, module, kind, name):
        return any(u.get('name') == name and (kind is None or u.get('type') == kind)
                   for u in self.unlocks.get(module, []) if isinstance(u, dict))

    def unlock_item(self, module, kind, name):
        if self.is_unlocked(module, kind, name):
            return
        entries = getattr(self.modules[module], 'unlocks', []) or []
        data = next((u for u in entries if u.get('name') == name and u.get('type') == kind), None)
        if not data:
            return
        self.unlocks.setdefault(module, []).append({'type': kind, 'name': name, 'label': data.get('label', name)})
        self.effects.append({'kind': 'unlock', 'module': module, 'type': kind, 'name': name, 'card': data.get('card')})
        for group in entries:
            if group.get('type') == 'group' and isinstance(group.get('list'), list):
                if all(self.is_unlocked(module, None, n) for n in group['list']):
                    self.unlock_item(module, 'group', group['name'])

    def discover(self, pet, reward):
        entry = {'name': pet.name, 'module': pet.module, 'version': pet.version}
        if entry not in self.digidex:
            self.digidex.append(entry)
            self.effects.append(dict(entry, kind='discovery'))
        if reward:
            self.effects.append(dict(entry, kind='evolution',
                                     id=f'{self.generation}:{pet.android_id}:{self.cursor}:{len(pet.evolution_history)}'))
        from utils.data_compat import availability
        known = {(e['name'], e['version']) for e in self.digidex if e['module'] == pet.module}
        count = 0
        for monster in self.modules[pet.module].get_all_monsters():
            kind = availability(monster)
            if kind == 'Unobtainable':
                continue
            if kind == 'Friend':
                count += monster['name'] in self.friends.get(pet.module, [])
            else:
                count += (monster['name'], monster['version']) in known
        for unlock in getattr(self.modules[pet.module], 'unlocks', []) or []:
            if unlock.get('type') == 'digidex' and unlock.get('amount') is not None and count >= unlock['amount']:
                self.unlock_item(pet.module, 'digidex', unlock['name'])

    def quest_evolution(self, module):
        from models.game_quest import QuestType, QuestStatus
        for quest in self.quests:
            if quest.status == QuestStatus.PENDING and quest.type == QuestType.EVOLUTION:
                quest.update_progress(1)

    def notice(self, pet, kind, title, body, event=None):
        self.sequence += 1
        data = {'id': f'{self.generation}:{self.sequence}', 'at': int(self.cursor * 1000),
                'kind': kind, 'title': title, 'body': body,
                'pet': pet.android_id if pet else '', 'event': event}
        self.notices.append(data)
        if pet and kind in ('call', 'sick', 'dying'):
            self.active_notices[(pet.android_id, kind)] = data

    def choose_friend(self):
        pending = self.friend_event_pending
        if not isinstance(pending, dict):
            return None
        pending['minutes'] -= 1
        if pending['minutes'] > 0:
            return None
        self.friend_event_pending = None
        pet = next((p for p in self.pet_list if p.name == pending.get('pet') and p.module == pending.get('module')), None)
        if pet is None or pet.state in ('dead', 'nap') or ailments.ailing(pet) or not pet.can_battle():
            return None
        names = []
        for evo in getattr(pet, 'temp_evolve', []):
            for name in evo.get('friend', []) or []:
                if name not in names and name not in self.friends.get(pet.module, []):
                    names.append(name)
        encounters = self.modules[pet.module].get_friend_encounters()
        choices = [(name, next((e for e in encounters if e.get('name') == name), None)) for name in names]
        choices = [(name, e) for name, e in choices if e]
        if not choices:
            return None
        name, enc = self.rng.choice(choices)
        from models.game_event import GameEvent, EventType
        return GameEvent(f'friend:{pet.module}:{name}', name, pet.module, False,
                         EventType.ENEMY_BATTLE, 100, enc['area'], enc['round'])

    def advance(self, target):
        if not math.isfinite(target) or target < self.cursor:
            return self
        # A party left off the main screen had not applied these minutes yet;
        # update() applies them as one batch on its next frame.
        for pet in self.pet_list:
            pending = pet.__dict__.pop('android_pending_minutes', 0)
            if pending > 0:
                pet._rt_last_minute -= pending
                pet.minute(pending)
        if target > self.cursor:
            # This action was already triggered before closing. Completing its
            # visual tail must not depend on another whole care minute passing.
            for pet in self.pet_list:
                if pet.state == 'pooping':
                    pet.poop()
        # No frame replay and no discarded elapsed-time cap. Empty parties are
        # terminal; with a live party only minute and calendar boundaries run.
        while self.pet_list:
            midnight = datetime.combine(self.now.date() + timedelta(days=1), datetime.min.time())
            if self.zone is not None:
                midnight = midnight.replace(tzinfo=self.zone)
            midnight = midnight.timestamp()
            boundary = min([p.next_minute for p in self.pet_list] + [self.next_event_minute, midnight])
            if boundary > target:
                break
            self.cursor = boundary
            if self.now.date() > self.xai_date:
                self.xai = self.rng.randint(1, 7)
                self.xai_date = self.now.date()
                self.quests = []
            for p in list(self.pet_list):
                if p.next_minute <= boundary:
                    p.next_minute += 60
                    p.minute()
            # Poop completes after this minute's health checks, before the
            # next minute can assess accumulated field sickness.
            for p in self.pet_list:
                if p.state == 'pooping':
                    p.poop()
                for kind, active, flags, title, body in (
                    ('call', p.call_sign(), self.calls, 'Pet needs attention', f'{p.name} needs care.'),
                    ('sick', ailments.ailing(p), self.sickness, 'Pet is sick', f'{p.name} needs medicine.'),
                    ('dying', p.dying, self.deaths, 'Pet needs urgent care', f'{p.name} is dying.'),
                ):
                    if active and not flags.get(p.android_id, False):
                        self.notice(p, kind, title, body)
                    if (not active or p.state == 'dead' or p.removed) and (p.android_id, kind) in self.active_notices:
                        self.active_notices.pop((p.android_id, kind))['validUntil'] = int(boundary * 1000)
                    flags[p.android_id] = bool(active)
            self.pet_list = [p for p in self.pet_list if not p.removed]
            if self.event is not None and boundary >= self.event_until:
                self.event = None
            if self.next_event_minute <= boundary:
                self.next_event_minute += 60
                before = self.event
                from utils.event_utils import scheduled_event
                EventClock.tick(self, lambda: EventClock.choose(self.pet_list, self.modules, self.xai, self.rng,
                                                                self.friends),
                                self.choose_friend, self.rng,
                                lambda: scheduled_event(self.pet_list, self.modules, self.now, self.rng,
                                                        self.friends))
                if self.event is not None and self.event is not before:
                    self.event_until = boundary + 60
                    self.notice(None, 'event', 'An event is waiting', self.event.name,
                                event_to_data(self.event))
        if self.event is not None and target >= self.event_until:
            self.event = None
        self.cursor = target
        return self


def event_to_data(event):
    if event is None:
        return None
    data = dict(event.__dict__)
    data['type'] = event.type.value
    return data


def event_from_data(data):
    from models.game_event import GameEvent, EventType
    return GameEvent(data['id'], data['name'], data['module'], data['global_event'],
                     EventType(data['type']), data['chance_percent'], data['area'],
                     data['round'], data.get('item', ''), data.get('item_quantity', 1),
                     data.get('shop', ''), data.get('access_minutes', 0), data.get('reward_round', 0),
                     data.get('opponent', ''), data.get('opponent_version', 0))
