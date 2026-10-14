"""Event timing/selection without animation; the scene retains its frame cadence."""
import random


class EventClock:
    FOREGROUND_SECONDS = 60
    NOTIFICATION_SECONDS = 300

    @staticmethod
    def tick(state, choose_event, choose_friend, rng=random, choose_scheduled=None):
        """One existing game minute. Pending events pause both countdowns.

        A promised Friend battle comes first, then a scheduled encounter due
        this minute (utils.event_utils.scheduled_event), then the hourly
        random roll."""
        if state.event is not None:
            return
        friend = choose_friend()
        if friend is not None:
            state.event = friend
            return
        if choose_scheduled is not None:
            scheduled = choose_scheduled()
            if scheduled is not None:
                state.event = scheduled
                return
        if state.event_time is None:
            state.event_time = 60
        state.event_time -= 1
        if state.event_time <= 0:
            if any(p.state not in ('dead', 'nap') for p in state.pet_list):
                state.event = choose_event()
            state.event_time = rng.randint(45, 75)

    @staticmethod
    def expired(alert_frames, frame_rate):
        return alert_frames >= frame_rate * EventClock.FOREGROUND_SECONDS

    @staticmethod
    def initial_alert(event, frame_rate):
        """Android recovery may carry an existing alert's remaining window."""
        remaining = event.__dict__.pop('android_remaining_seconds', EventClock.FOREGROUND_SECONDS)
        silent = event.__dict__.pop('android_silent_arrival', False)
        return int(max(0, EventClock.FOREGROUND_SECONDS - remaining) * frame_rate), silent

    @staticmethod
    def choose(pets, modules, xai, rng=random, friends=None):
        """Same XAI/module/weighted selection used by foreground random events.
        Only "random"-trigger events take part (utils.event_utils); the one
        drawn is resolved there (a Friend battle, a pooled encounter...)."""
        from utils.event_utils import random_events, resolve
        if rng.randint(1, 100) > min(70, xai * 10):
            return None
        party = {p.module for p in pets}
        candidates = []
        for name, module in modules.items():
            entries = random_events(module, name in party)
            if entries:
                candidates.append((name, entries))
        if not candidates:
            return None
        name, entries = rng.choice(candidates)
        total = sum(e.chance_percent for e in entries)
        if total <= 0:
            return None
        roll = rng.randint(1, min(100, total))
        for e in entries:
            roll -= e.chance_percent
            if roll <= 0:
                return resolve(name, modules[name], e, pets, rng, friends)
