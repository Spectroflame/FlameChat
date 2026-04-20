"""Acoustic audio analysis — loudness, peaks, dynamics, spectrum.

Produces the kind of report a blind mix engineer would want: objective
numbers plus one-sentence interpretations ("loud, consistent with a
modern streaming master"). Written from scratch for FlameChat but
shaped by the metrics catalogue of NonvisualAudio (LUFS-I, true peak,
loudness range, crest factor, band energies).

Decoding goes through PyAV, which bundles its own FFmpeg libraries in
the wheel. That means we handle every format (MP3, M4A/AAC, WAV, FLAC,
OGG, Opus, AIFF) out of the box without needing a system ffmpeg binary
or libsndfile extensions — the old soundfile-with-ffmpeg-fallback route
reliably failed on M4A because libsndfile has no AAC decoder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class AudioReport:
    file_name: str
    duration_s: float
    sample_rate: int
    channels: int
    bit_depth: int | None
    integrated_lufs: float | None
    true_peak_dbtp: float | None
    loudness_range_lu: float | None
    crest_factor_db: float
    band_energies: dict[str, float]  # key -> relative dB
    dc_offset: float
    clipping_samples: int

    def as_text(self) -> str:
        """Screen-reader-friendly plain-text report."""
        lines: list[str] = []
        lines.append(f"Datei: {self.file_name}")
        lines.append(
            f"Dauer: {_fmt_duration(self.duration_s)}  ·  "
            f"{self.sample_rate} Hz  ·  "
            f"{self.channels} Kanal{'e' if self.channels != 1 else ''}"
            + (f"  ·  {self.bit_depth} Bit" if self.bit_depth else "")
        )
        lines.append("")
        lines.append("Lautheit:")
        if self.integrated_lufs is not None:
            lines.append(
                f"  Integrated Loudness: {self.integrated_lufs:.1f} LUFS "
                f"({_loudness_verdict(self.integrated_lufs)})"
            )
        if self.true_peak_dbtp is not None:
            lines.append(
                f"  True Peak: {self.true_peak_dbtp:.1f} dBTP "
                f"({_true_peak_verdict(self.true_peak_dbtp)})"
            )
        if self.loudness_range_lu is not None:
            lines.append(
                f"  Loudness Range: {self.loudness_range_lu:.1f} LU "
                f"({_lra_verdict(self.loudness_range_lu)})"
            )
        lines.append("")
        lines.append("Dynamik:")
        lines.append(
            f"  Crest-Faktor: {self.crest_factor_db:.1f} dB "
            f"({_crest_verdict(self.crest_factor_db)})"
        )
        lines.append(f"  Gleichspannungs-Offset: {self.dc_offset:+.4f}")
        if self.clipping_samples:
            lines.append(
                f"  Digital geclippte Samples: {self.clipping_samples} "
                "(Achtung — hörbare Verzerrung möglich)"
            )
        else:
            lines.append("  Keine geclippten Samples gefunden.")
        lines.append("")
        lines.append("Frequenzbänder (relativ zum Gesamtpegel):")
        for name, level in self.band_energies.items():
            lines.append(f"  {name:10s}: {level:+5.1f} dB")
        return "\n".join(lines)


def analyze(path: Path) -> AudioReport:
    samples, sample_rate, channels, bit_depth = _load_audio(path)
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples

    duration_s = len(mono) / sample_rate

    integrated_lufs, loudness_range_lu = _loudness_metrics(samples, sample_rate)
    true_peak_dbtp = _true_peak_db(mono)
    crest_factor_db = _crest_factor_db(mono)
    dc_offset = float(np.mean(mono))
    clipping_samples = int(np.sum(np.abs(mono) >= 0.999))
    band_energies = _band_energies(mono, sample_rate)

    return AudioReport(
        file_name=path.name,
        duration_s=duration_s,
        sample_rate=sample_rate,
        channels=channels,
        bit_depth=bit_depth,
        integrated_lufs=integrated_lufs,
        true_peak_dbtp=true_peak_dbtp,
        loudness_range_lu=loudness_range_lu,
        crest_factor_db=crest_factor_db,
        band_energies=band_energies,
        dc_offset=dc_offset,
        clipping_samples=clipping_samples,
    )


# --- internals ---------------------------------------------------------

def _load_audio(path: Path) -> tuple[np.ndarray, int, int, int | None]:
    """Return (samples float32 -1..1, sample_rate, channels, bit_depth).

    Downmixes anything beyond stereo to stereo — loudness, true-peak and
    spectrum analysis only need mono or stereo, and pyloudnorm refuses
    anything higher.
    """
    import av  # local import — ships with faster-whisper

    try:
        container = av.open(str(path))
    except av.AVError as e:
        raise RuntimeError(
            f"Audio konnte nicht geöffnet werden ({path.name}): {e}"
        ) from e

    try:
        if not container.streams.audio:
            raise RuntimeError(
                f"In „{path.name}“ wurde keine Audiospur gefunden."
            )
        stream = container.streams.audio[0]
        sample_rate = int(stream.rate)
        src_channels = int(stream.channels or 1)
        target_channels = 1 if src_channels == 1 else 2
        target_layout = "mono" if target_channels == 1 else "stereo"
        bit_depth = _av_bit_depth(stream)

        resampler = av.AudioResampler(
            format="flt",  # packed 32-bit float
            layout=target_layout,
            rate=sample_rate,
        )
        pieces: list[np.ndarray] = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                pieces.append(
                    resampled.to_ndarray().reshape(-1, target_channels)
                )
        # Flush any buffered samples from the resampler.
        for resampled in resampler.resample(None):
            pieces.append(resampled.to_ndarray().reshape(-1, target_channels))
    finally:
        container.close()

    if not pieces:
        data = np.zeros((0, target_channels), dtype=np.float32)
    else:
        data = np.concatenate(pieces, axis=0).astype(np.float32)
    return data, sample_rate, target_channels, bit_depth


def _av_bit_depth(stream) -> int | None:
    """Best-effort bit-depth from an av.AudioStream (None if unclear)."""
    try:
        fmt = stream.codec_context.format
        if fmt is None:
            return None
        bits = getattr(fmt, "bits", None)
        if bits:
            return int(bits)
        # AAC / MP3 / Opus are lossy: PyAV reports the decoder output
        # width (often 32-bit float), not the source. Surfacing that
        # would mislead, so we return None for known-lossy codecs.
        return None
    except Exception:
        return None


def _loudness_metrics(samples: np.ndarray, sample_rate: int) -> tuple[float | None, float | None]:
    try:
        import pyloudnorm as pyln  # local import
    except ImportError:
        return None, None
    try:
        meter = pyln.Meter(sample_rate)
        integrated = meter.integrated_loudness(samples)
        # Loudness range = difference between 95th and 10th percentile of
        # short-term momentary loudness. pyloudnorm exposes it via
        # the EBU R 128 compliant `loudness_range_tech_3342` helper —
        # available from 0.1.1 upward.
        try:
            lra = pyln.loudness_range(samples, sample_rate)  # type: ignore[attr-defined]
        except AttributeError:
            lra = None
        return float(integrated), (float(lra) if lra is not None else None)
    except (ValueError, RuntimeError):
        return None, None


def _true_peak_db(mono: np.ndarray) -> float | None:
    """Oversampled peak approximation — good enough for a feedback label."""
    if mono.size == 0:
        return None
    from scipy.signal import resample_poly  # local import

    up = resample_poly(mono, up=4, down=1)
    peak = float(np.max(np.abs(up)))
    if peak <= 0.0:
        return -float("inf")
    return 20.0 * np.log10(peak)


def _crest_factor_db(mono: np.ndarray) -> float:
    if mono.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(mono)))
    if rms <= 1e-12 or peak <= 1e-12:
        return 0.0
    return 20.0 * np.log10(peak / rms)


def _band_energies(mono: np.ndarray, sample_rate: int) -> dict[str, float]:
    """Relative dB energy in six standard bands."""
    if mono.size == 0:
        return {}
    from scipy.signal import welch  # local import

    freqs, psd = welch(mono, fs=sample_rate, nperseg=min(8192, mono.size))
    total = float(np.sum(psd))
    if total <= 0:
        return {}

    bands = [
        ("sub",     20,   60),
        ("bass",    60,   250),
        ("low-mid", 250,  500),
        ("mid",     500,  2000),
        ("presence",2000, 6000),
        ("air",     6000, 20000),
    ]
    out: dict[str, float] = {}
    for name, lo, hi in bands:
        mask = (freqs >= lo) & (freqs < hi)
        band_e = float(np.sum(psd[mask]))
        if band_e <= 0:
            out[name] = -120.0
            continue
        out[name] = 10.0 * np.log10(band_e / total)
    return out


# --- interpretive one-liners -------------------------------------------

def _loudness_verdict(lufs: float) -> str:
    if lufs > -9:
        return "sehr laut, jenseits von Streaming-Normen"
    if lufs > -14:
        return "typisch für kommerzielle Produktionen"
    if lufs > -18:
        return "moderat laut"
    if lufs > -24:
        return "dynamisch, spricht für Film/Hörbuch"
    return "sehr leise — Pegel prüfen"


def _true_peak_verdict(dbtp: float) -> str:
    if dbtp > -0.3:
        return "kritisch — praktisch an der Clipping-Grenze"
    if dbtp > -1.0:
        return "hoch — nicht mehr viel Luft nach oben"
    if dbtp > -3.0:
        return "im üblichen Bereich"
    return "reichlich Headroom"


def _lra_verdict(lra: float) -> str:
    if lra < 3:
        return "stark komprimiert, sehr gleichmäßig"
    if lra < 6:
        return "moderat verdichtet"
    if lra < 10:
        return "natürliche Dynamik"
    return "sehr dynamisch, klassik-/filmmusik-typisch"


def _crest_verdict(db: float) -> str:
    if db < 6:
        return "stark limitiert"
    if db < 10:
        return "typisch für moderne Produktionen"
    if db < 15:
        return "noch hörbare Transienten"
    return "hohe Dynamik, viele Transienten"


def _fmt_duration(seconds: float) -> str:
    minutes, s = divmod(int(round(seconds)), 60)
    hours, m = divmod(minutes, 60)
    if hours:
        return f"{hours}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"
