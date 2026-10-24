"""Reconstruct the long Xros-evolution cue from its reference recording.

The cue is a repeating seven-pulse motif, clipped at partial cycles at the
beginning and end of the recording.  Its individual pulse spectra vary, so the
reference is restored rather than replaced with guessed oscillators: a noise
profile is learned from the silent gaps, subtracted in the STFT domain, and the
detected pulse regions are retained with short cosine edges.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_closing, label
from scipy.signal import istft, stft


SAMPLE_RATE = 44_100
DURATION_SECONDS = 5.4
RMS_WINDOW_SECONDS = 0.004
ACTIVE_RMS_THRESHOLD = 0.018
MIN_PULSE_SECONDS = 0.045
CLOSE_GAP_SECONDS = 0.006
EDGE_SECONDS = 0.003
STFT_SAMPLES = 1_024
STFT_OVERLAP_SAMPLES = 768
NOISE_SUBTRACTION = 1.5
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
            raise ValueError("Xros-evolution reference must be mono 16-bit 44.1 kHz PCM")
        samples = np.frombuffer(
            wav_file.readframes(wav_file.getnframes()), dtype="<i2"
        ).astype(np.float64)
    expected = round(SAMPLE_RATE * DURATION_SECONDS)
    if len(samples) != expected:
        raise ValueError(
            f"Expected {DURATION_SECONDS:.1f}s reference, got "
            f"{len(samples) / SAMPLE_RATE:.6f}s"
        )
    return samples


def _pulse_regions(samples: np.ndarray) -> list[tuple[int, int]]:
    window_samples = round(SAMPLE_RATE * RMS_WINDOW_SECONDS)
    rms = np.sqrt(np.convolve(
        samples * samples,
        np.ones(window_samples) / window_samples,
        mode="same",
    ))
    active = rms > (ACTIVE_RMS_THRESHOLD * 32_768)
    close_samples = round(SAMPLE_RATE * CLOSE_GAP_SECONDS)
    active = binary_closing(active, structure=np.ones(close_samples, dtype=bool))
    labels, count = label(active)
    min_samples = round(SAMPLE_RATE * MIN_PULSE_SECONDS)
    edge_samples = round(SAMPLE_RATE * EDGE_SECONDS)
    regions = []
    for region_id in range(1, count + 1):
        indices = np.flatnonzero(labels == region_id)
        if len(indices) < min_samples:
            continue
        start = max(0, int(indices[0]) - edge_samples)
        end = min(len(samples), int(indices[-1]) + 1 + edge_samples)
        regions.append((start, end))
    return regions


def _frequency_mask(frequencies: np.ndarray) -> np.ndarray:
    mask = np.ones_like(frequencies)
    mask[frequencies <= LOW_CUTOFF_HZ] = 0.0
    low = (frequencies > LOW_CUTOFF_HZ) & (frequencies < LOW_PASSBAND_HZ)
    low_progress = (
        (frequencies[low] - LOW_CUTOFF_HZ)
        / (LOW_PASSBAND_HZ - LOW_CUTOFF_HZ)
    )
    mask[low] = np.sin(low_progress * np.pi / 2.0) ** 2

    mask[frequencies >= HIGH_CUTOFF_HZ] = 0.0
    high = (
        (frequencies > HIGH_PASSBAND_HZ)
        & (frequencies < HIGH_CUTOFF_HZ)
    )
    high_progress = (
        (frequencies[high] - HIGH_PASSBAND_HZ)
        / (HIGH_CUTOFF_HZ - HIGH_PASSBAND_HZ)
    )
    mask[high] = np.cos(high_progress * np.pi / 2.0) ** 2
    return mask


def _spectral_denoise(samples: np.ndarray, regions: list[tuple[int, int]]) -> np.ndarray:
    frequencies, times, spectrum = stft(
        samples,
        fs=SAMPLE_RATE,
        nperseg=STFT_SAMPLES,
        noverlap=STFT_OVERLAP_SAMPLES,
        boundary="zeros",
        padded=True,
    )
    active_frames = np.zeros(len(times), dtype=bool)
    for start, end in regions:
        active_frames |= (times >= start / SAMPLE_RATE) & (times <= end / SAMPLE_RATE)
    noise_frames = ~active_frames
    if not np.any(noise_frames):
        raise ValueError("Reference has no silent frames for noise estimation")

    power = np.abs(spectrum) ** 2
    noise_power = np.median(power[:, noise_frames], axis=1, keepdims=True)
    retained_power = np.maximum(power - NOISE_SUBTRACTION * noise_power, 0.0)
    gain = np.sqrt(retained_power / np.maximum(power, 1e-20))
    cleaned_spectrum = spectrum * gain * _frequency_mask(frequencies)[:, None]
    _, cleaned = istft(
        cleaned_spectrum,
        fs=SAMPLE_RATE,
        nperseg=STFT_SAMPLES,
        noverlap=STFT_OVERLAP_SAMPLES,
        input_onesided=True,
        boundary=True,
    )
    return cleaned[:len(samples)]


def _pulse_gate(length: int, regions: list[tuple[int, int]]) -> np.ndarray:
    gate = np.zeros(length, dtype=np.float64)
    edge_samples = round(SAMPLE_RATE * EDGE_SECONDS)
    edge = np.sin(np.linspace(0.0, np.pi / 2.0, edge_samples)) ** 2
    for start, end in regions:
        gate[start:end] = 1.0
        fade_length = min(edge_samples, (end - start) // 2)
        gate[start:start + fade_length] *= edge[:fade_length]
        gate[end - fade_length:end] *= edge[:fade_length][::-1]
    return gate


def generate(output_path: Path, reference_path: Path) -> None:
    reference = _load_reference(reference_path)
    regions = _pulse_regions(reference)
    cleaned = _spectral_denoise(reference, regions)
    cleaned *= _pulse_gate(len(cleaned), regions)

    peak = np.max(np.abs(cleaned))
    if peak == 0:
        raise ValueError("Xros-evolution reference contains no usable signal")
    cleaned *= TARGET_PEAK / peak
    pcm = np.clip(np.rint(cleaned), -32_768, 32_767).astype("<i2")

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
        sounds_dir / "23.wav",
        sounds_dir / "source_backups" / "23_xros_evolution_recording.wav",
    )
