"""Generate the clean Xros-start cue used by the DMC sound set.

Unlike the regular DMC square-wave beeps, the source cue has a rough 70 Hz
tremolo and starts with a metallic mix dominated by high odd harmonics.  Those
harmonics recede during its one-octave rise, leaving a more focused fundamental.
This additive reconstruction preserves that character without retaining the
microphone noise or room coloration of the reference recording.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 44_100
DURATION_SECONDS = 1.1
TONE_START_SECONDS = 0.46
SWEEP_START_SECONDS = 0.68
TONE_END_SECONDS = 1.025
START_FREQUENCY_HZ = 1_312.5
END_FREQUENCY_HZ = 2_625.0
TREMOLO_FREQUENCY_HZ = 70.0
TREMOLO_DEPTH = 0.88
ATTACK_SECONDS = 0.008
RELEASE_SECONDS = 0.018
POSITIVE_AMPLITUDE = 32_767
NEGATIVE_AMPLITUDE = -32_768

# Harmonic numbers 1, 3, 5 and 7.  The reference begins thin and metallic,
# then transitions toward its fundamental as the sweep rises.
START_HARMONIC_WEIGHTS = (0.20, 0.62, 1.00, 0.92)
END_HARMONIC_WEIGHTS = (1.00, 0.34, 0.10, 0.02)


def _frequency_at(time_seconds: float) -> float:
    if time_seconds <= SWEEP_START_SECONDS:
        return START_FREQUENCY_HZ
    sweep_progress = (
        (time_seconds - SWEEP_START_SECONDS)
        / (TONE_END_SECONDS - SWEEP_START_SECONDS)
    )
    return START_FREQUENCY_HZ + (
        END_FREQUENCY_HZ - START_FREQUENCY_HZ
    ) * sweep_progress


def _sweep_progress(time_seconds: float) -> float:
    if time_seconds <= SWEEP_START_SECONDS:
        return 0.0
    return min(
        1.0,
        (time_seconds - SWEEP_START_SECONDS)
        / (TONE_END_SECONDS - SWEEP_START_SECONDS),
    )


def _harmonic_weights(progress: float) -> tuple[float, ...]:
    return tuple(
        start + (end - start) * progress
        for start, end in zip(START_HARMONIC_WEIGHTS, END_HARMONIC_WEIGHTS)
    )


def generate(output_path: Path) -> None:
    sample_count = round(SAMPLE_RATE * DURATION_SECONDS)
    tone_start = round(SAMPLE_RATE * TONE_START_SECONDS)
    tone_end = round(SAMPLE_RATE * TONE_END_SECONDS)
    floating_samples = [0.0] * sample_count
    phase = 0.0

    # Align the first tremolo crest about 10 ms after onset, matching the
    # reference's repeating pulse envelope.
    tremolo_phase = (
        math.pi / 2.0
        - 2.0 * math.pi * TREMOLO_FREQUENCY_HZ * 0.010
    )

    for sample_index in range(tone_start, tone_end):
        time_seconds = sample_index / SAMPLE_RATE
        frequency = _frequency_at(time_seconds)
        phase += 2.0 * math.pi * frequency / SAMPLE_RATE
        progress = _sweep_progress(time_seconds)
        weights = _harmonic_weights(progress)
        tone = sum(
            weight * math.sin(harmonic * phase)
            for harmonic, weight in zip((1, 3, 5, 7), weights)
        )

        # Keep perceived energy stable while the harmonic balance changes.
        tone /= math.sqrt(sum(weight * weight for weight in weights))
        tremolo = (
            1.0 - TREMOLO_DEPTH
            + TREMOLO_DEPTH * 0.5 * (
                1.0 + math.sin(
                    2.0 * math.pi * TREMOLO_FREQUENCY_HZ
                    * (time_seconds - TONE_START_SECONDS)
                    + tremolo_phase
                )
            )
        )
        attack = min(1.0, (time_seconds - TONE_START_SECONDS) / ATTACK_SECONDS)
        release = min(1.0, (TONE_END_SECONDS - time_seconds) / RELEASE_SECONDS)
        floating_samples[sample_index] = tone * tremolo * min(attack, release)

    peak = max(abs(sample) for sample in floating_samples)
    scale = POSITIVE_AMPLITUDE / peak
    samples = [
        max(NEGATIVE_AMPLITUDE, min(POSITIVE_AMPLITUDE, round(sample * scale)))
        for sample in floating_samples
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    generate(project_root / "assets" / "dmc_sounds" / "21.wav")
