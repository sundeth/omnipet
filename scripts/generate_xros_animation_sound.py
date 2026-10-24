"""Reconstruct the two-burst X-animation cue from its reference recording.

The two bursts in the recording are sample-aligned repetitions of a deliberately
modulated waveform.  Coherent averaging keeps that repeatable pitch/harmonic
motion while cancelling part of the microphone noise.  A soft spectral window
then removes rumble and high-frequency recording noise before the result is
normalised to the DMC sound-set level.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 44_100
DURATION_SECONDS = 1.2
BEEP_STARTS_SECONDS = (0.285, 0.910)
BEEP_DURATION_SECONDS = 0.235
FADE_SECONDS = 0.003
LOW_CUTOFF_HZ = 900.0
LOW_PASSBAND_HZ = 1_400.0
HIGH_PASSBAND_HZ = 12_500.0
HIGH_CUTOFF_HZ = 14_000.0
TARGET_PEAK = 32_767


def _load_reference(reference_path: Path) -> np.ndarray:
    with wave.open(str(reference_path), "rb") as wav_file:
        if (wav_file.getnchannels() != 1
                or wav_file.getsampwidth() != 2
                or wav_file.getframerate() != SAMPLE_RATE):
            raise ValueError("X-animation reference must be mono 16-bit 44.1 kHz PCM")
        return np.frombuffer(
            wav_file.readframes(wav_file.getnframes()), dtype="<i2"
        ).astype(np.float64)


def _spectral_cleanup(samples: np.ndarray) -> np.ndarray:
    spectrum = np.fft.rfft(samples)
    frequencies = np.fft.rfftfreq(len(samples), 1.0 / SAMPLE_RATE)
    mask = np.ones_like(frequencies)

    mask[frequencies <= LOW_CUTOFF_HZ] = 0.0
    low_transition = (
        (frequencies > LOW_CUTOFF_HZ)
        & (frequencies < LOW_PASSBAND_HZ)
    )
    low_progress = (
        (frequencies[low_transition] - LOW_CUTOFF_HZ)
        / (LOW_PASSBAND_HZ - LOW_CUTOFF_HZ)
    )
    mask[low_transition] = np.sin(low_progress * np.pi / 2.0) ** 2

    mask[frequencies >= HIGH_CUTOFF_HZ] = 0.0
    high_transition = (
        (frequencies > HIGH_PASSBAND_HZ)
        & (frequencies < HIGH_CUTOFF_HZ)
    )
    high_progress = (
        (frequencies[high_transition] - HIGH_PASSBAND_HZ)
        / (HIGH_CUTOFF_HZ - HIGH_PASSBAND_HZ)
    )
    mask[high_transition] = np.cos(high_progress * np.pi / 2.0) ** 2

    return np.fft.irfft(spectrum * mask, n=len(samples))


def generate(output_path: Path, reference_path: Path) -> None:
    sample_count = round(SAMPLE_RATE * DURATION_SECONDS)
    beep_samples = round(SAMPLE_RATE * BEEP_DURATION_SECONDS)
    reference = _load_reference(reference_path)
    bursts = []

    for start_seconds in BEEP_STARTS_SECONDS:
        start = round(SAMPLE_RATE * start_seconds)
        burst = reference[start:start + beep_samples]
        if len(burst) != beep_samples:
            raise ValueError("X-animation reference is shorter than expected")
        bursts.append(burst)

    # The repeats are already aligned at zero lag.  Their coherent average
    # retains the intentional modulation and reduces uncorrelated recording
    # noise by approximately 3 dB.
    clean_burst = _spectral_cleanup(np.mean(bursts, axis=0))

    fade_samples = round(SAMPLE_RATE * FADE_SECONDS)
    fade = np.sin(np.linspace(0.0, np.pi / 2.0, fade_samples)) ** 2
    clean_burst[:fade_samples] *= fade
    clean_burst[-fade_samples:] *= fade[::-1]

    peak = np.max(np.abs(clean_burst))
    if peak == 0:
        raise ValueError("X-animation reference contains no usable signal")
    clean_burst *= TARGET_PEAK / peak

    samples = np.zeros(sample_count, dtype=np.float64)

    for start_seconds in BEEP_STARTS_SECONDS:
        start = round(SAMPLE_RATE * start_seconds)
        samples[start:start + beep_samples] = clean_burst

    pcm = np.clip(np.rint(samples), -32_768, 32_767).astype("<i2")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    sounds_dir = project_root / "assets" / "dmc_sounds"
    generate(
        sounds_dir / "22.wav",
        sounds_dir / "source_backups" / "22_xros_animation_recording.wav",
    )
