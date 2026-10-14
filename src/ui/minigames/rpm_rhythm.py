"""Deterministic approximation of the iC's rhythm charge.

The September 2026 recordings establish a recent-speed readout and a separate
bar meter. They do not reveal the firmware's timing windows. The calibration
below is deliberately explicit; see utilities/claude/docs/design/ic_rpm.md for the evidence
and limitations. Times are milliseconds since the charge screen opened.
"""

CHARGE_MS = 6000
MAX_BARS = 10
MAX_RPM = 99

# Approximate display calibration from motion intervals: 200 ms -> 90,
# 300 ms -> 70, 400 ms -> 50, 650 ms -> 0. Not literal revolutions/minute.
ZERO_RPM_INTERVAL_MS = 650
MS_PER_RPM = 5
RPM_STEP = 5

# Model choices, not recovered device constants. Lower bars accept a wider
# pace range; the last bar asks for the pet's preferred pace. Comparing with
# recent cadence also prevents irregular bursts from scoring as steady taps.
SLOW_ALLOWANCE_PER_BAR_MS = 25
PACE_TOLERANCE_MS = 30
FAST_INTERVAL_RATIO = 0.4
FAST_RATIO_PER_BAR = 0.04
CADENCE_TOLERANCE = 0.35
TOLERANCE_REDUCTION_PER_BAR = 0.015
MIN_TOLERANCE_MS = 30
CADENCE_ADAPTATION = 0.25
MIN_PRESS_INTERVAL_MS = 60


def rpm_for_interval(interval_ms):
    """Recent press spacing on the observed 0, 5, ... 95, 99 display."""
    if interval_ms is None:
        return 0
    value = (ZERO_RPM_INTERVAL_MS - interval_ms) / MS_PER_RPM
    stepped = int(max(0, value) / RPM_STEP + 0.5) * RPM_STEP
    return min(MAX_RPM, stepped)


class RPMRhythm:
    """Charge history, independent of rendering, frame rate and input device."""

    def __init__(self, target=55):
        self.target = max(1, min(MAX_RPM, int(target or 55)))
        self.target_interval = ZERO_RPM_INTERVAL_MS - self.target * MS_PER_RPM
        self.press_times = []
        self.elapsed_ms = 0
        self.bars = 0
        self.rpm = 0
        self.last_interval = None
        self.cadence = None
        self.misses = 0
        self._next_miss = None
        self._timed_out = False

    def _tolerance(self):
        return max(MIN_TOLERANCE_MS, self.cadence * (
            CADENCE_TOLERANCE - self.bars * TOLERANCE_REDUCTION_PER_BAR))

    def _miss(self):
        # The first miss stalls the meter; continued misses lose progress.
        self.misses += 1
        if self.misses >= 2:
            self.bars = max(0, self.bars - 1)

    def advance(self, elapsed_ms):
        """Account for missed beats up to the deadline, once each.

        Crossing the deadline on a slow frame still settles at exactly the
        deadline. Neither post-charge blinking nor a frame stall extends play.
        """
        now = max(self.elapsed_ms, min(CHARGE_MS, int(elapsed_ms)))
        while self._next_miss is not None and now > self._next_miss:
            self._miss()
            self._timed_out = True
            self._next_miss += self.cadence
        if self.last_interval is not None:
            interval = max(self.last_interval, now - self.press_times[-1])
            self.rpm = rpm_for_interval(interval)
        self.elapsed_ms = now

    def press(self, elapsed_ms):
        """Register a distinct press; return whether it was accepted."""
        at = int(elapsed_ms)
        if at < self.elapsed_ms or at < 0 or at >= CHARGE_MS:
            self.advance(at)
            return False
        self.advance(at)
        if self.press_times and at - self.press_times[-1] < MIN_PRESS_INTERVAL_MS:
            return False
        previous = self.press_times[-1] if self.press_times else None
        self.press_times.append(at)
        if previous is None:
            # One press establishes a timestamp, not a speed or a rhythm.
            return True

        interval = at - previous
        self.last_interval = interval
        self.rpm = rpm_for_interval(interval)
        if self.cadence is None:
            self.cadence = min(ZERO_RPM_INTERVAL_MS, interval)

        next_bar = min(MAX_BARS, self.bars + 1)
        fastest = self.target_interval * (
            FAST_INTERVAL_RATIO + FAST_RATIO_PER_BAR * next_bar)
        slowest = self.target_interval + PACE_TOLERANCE_MS + (
            MAX_BARS - next_bar) * SLOW_ALLOWANCE_PER_BAR_MS
        in_rhythm = abs(interval - self.cadence) <= self._tolerance()
        in_pace = fastest <= interval <= slowest and self.rpm > 0
        if not self._timed_out and in_rhythm and in_pace:
            self.bars = next_bar
            self.misses = 0
        elif not self._timed_out:
            # An overdue beat was already penalized by advance().
            self._miss()

        # Learn changes in cadence gradually, including a return after a pause.
        observed = min(ZERO_RPM_INTERVAL_MS, interval)
        self.cadence += CADENCE_ADAPTATION * (observed - self.cadence)
        self._next_miss = at + self.cadence + self._tolerance()
        self._timed_out = False
        return True

    def bars_for_target(self, target):
        """Replay the same input for another training pet's preferred pace."""
        if int(target or 55) == self.target:
            return self.bars
        other = type(self)(target)
        for at in self.press_times:
            other.press(at)
        other.advance(self.elapsed_ms)
        return other.bars
