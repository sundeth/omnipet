"""Generate the four-second training ready cue used by the DMC sound set."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 44_100
DURATION_SECONDS = 4.0
LOW_BEEP_DURATION_SECONDS = 0.5
HIGH_BEEP_DURATION_SECONDS = 0.75
BEEP_INTERVAL_SECONDS = 1.0
LOW_HALF_PERIOD_SAMPLES = 8
HIGH_FREQUENCY_HZ = 4_010
POSITIVE_AMPLITUDE = 32_767
NEGATIVE_AMPLITUDE = -32_768


def generate(output_path: Path) -> None:
    sample_count = round(SAMPLE_RATE * DURATION_SECONDS)
    samples = [0] * sample_count

    for beep_index in range(4):
        start = round(SAMPLE_RATE * BEEP_INTERVAL_SECONDS * beep_index)
        is_final_beep = beep_index == 3
        beep_duration = HIGH_BEEP_DURATION_SECONDS if is_final_beep else LOW_BEEP_DURATION_SECONDS
        beep_samples = round(SAMPLE_RATE * beep_duration)
        for offset in range(beep_samples):
            if is_final_beep:
                phase = 2.0 * math.pi * HIGH_FREQUENCY_HZ * offset / SAMPLE_RATE
                positive_half_cycle = math.sin(phase) >= 0
            else:
                positive_half_cycle = (offset // LOW_HALF_PERIOD_SAMPLES) % 2 == 0
            samples[start + offset] = (
                POSITIVE_AMPLITUDE if positive_half_cycle else NEGATIVE_AMPLITUDE
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    generate(project_root / "assets" / "dmc_sounds" / "20.wav")
