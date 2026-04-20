"""Detect RAM, CPU and GPU class so we can recommend appropriately sized models.

Runs read-only commands. On Apple Silicon the GPU shares system RAM, so we
report unified memory and flag ``unified_memory=True``. On dedicated-GPU
machines we try ``nvidia-smi`` (NVIDIA) and ``rocm-smi`` (AMD). If nothing
matches we fall back to CPU-only.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

import psutil


GpuVendor = Literal["none", "nvidia", "amd", "apple", "intel"]


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str
    cpu_cores_logical: int
    cpu_cores_physical: int
    total_ram_gb: float
    gpu_vendor: GpuVendor
    gpu_name: str
    gpu_vram_gb: float
    unified_memory: bool  # True on Apple Silicon; VRAM effectively == RAM

    @property
    def effective_vram_gb(self) -> float:
        """The memory budget we actually have for loading a model."""
        if self.unified_memory:
            # Leave ~25% headroom for the OS + other apps on unified memory.
            return max(0.0, self.total_ram_gb * 0.75)
        if self.gpu_vram_gb > 0:
            return self.gpu_vram_gb
        return max(0.0, self.total_ram_gb * 0.6)  # CPU-only, be conservative


def _friendly_os_name() -> str:
    """Return a display-friendly OS label (e.g. ``'macOS 15.7.4'``).

    ``platform.system()`` returns the kernel identity — ``Darwin`` on
    macOS and ``Linux`` on every Linux flavour — which is not what end
    users want to see. We translate to the marketing name and append
    the release version everyone actually recognises.
    """
    if sys.platform == "darwin":
        version = platform.mac_ver()[0]
        return f"macOS {version}" if version else "macOS"
    if sys.platform == "win32":
        # platform.release() returns '10', '11', etc. which is what users call it.
        return f"Windows {platform.release()}"
    # Linux: try to pull the distro pretty name from /etc/os-release,
    # fall back to the kernel release.
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            mapping = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    mapping[k] = v.strip().strip('"')
        pretty = mapping.get("PRETTY_NAME") or mapping.get("NAME")
        if pretty:
            return pretty
    except OSError:
        pass
    return f"Linux {platform.release()}"


def _detect_nvidia() -> tuple[str, float] | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            text=True,
            timeout=3,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    first = out.strip().splitlines()[0] if out.strip() else ""
    if not first:
        return None
    name, mem_mib = [x.strip() for x in first.split(",", 1)]
    try:
        return name, float(mem_mib) / 1024.0
    except ValueError:
        return None


def _detect_amd() -> tuple[str, float] | None:
    if not shutil.which("rocm-smi"):
        return None
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--csv"],
            text=True,
            timeout=3,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    # rocm-smi CSV is loosely structured; best-effort parse.
    name = "AMD GPU"
    vram_gb = 0.0
    for line in out.splitlines():
        if "Card series" in line or "Card model" in line:
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip():
                name = parts[1].strip()
        if "VRAM Total Memory" in line:
            parts = line.split(",")
            for p in parts[::-1]:
                p = p.strip()
                if p.isdigit():
                    vram_gb = int(p) / (1024**3)
                    break
    return (name, vram_gb) if vram_gb else None


def _detect_apple_silicon() -> str | None:
    if platform.system() != "Darwin":
        return None
    # arch is "arm64" on Apple Silicon, "x86_64" on Intel Macs.
    if platform.machine() != "arm64":
        return None
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=2
        )
        return out.strip() or "Apple Silicon"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return "Apple Silicon"


def detect() -> HardwareProfile:
    vm = psutil.virtual_memory()
    total_ram_gb = vm.total / (1024**3)
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or logical
    os_name = _friendly_os_name()

    if apple := _detect_apple_silicon():
        return HardwareProfile(
            os_name=os_name,
            cpu_cores_logical=logical,
            cpu_cores_physical=physical,
            total_ram_gb=total_ram_gb,
            gpu_vendor="apple",
            gpu_name=apple,
            gpu_vram_gb=0.0,
            unified_memory=True,
        )
    if nv := _detect_nvidia():
        name, vram = nv
        return HardwareProfile(
            os_name=os_name,
            cpu_cores_logical=logical,
            cpu_cores_physical=physical,
            total_ram_gb=total_ram_gb,
            gpu_vendor="nvidia",
            gpu_name=name,
            gpu_vram_gb=vram,
            unified_memory=False,
        )
    if amd := _detect_amd():
        name, vram = amd
        return HardwareProfile(
            os_name=os_name,
            cpu_cores_logical=logical,
            cpu_cores_physical=physical,
            total_ram_gb=total_ram_gb,
            gpu_vendor="amd",
            gpu_name=name,
            gpu_vram_gb=vram,
            unified_memory=False,
        )
    return HardwareProfile(
        os_name=os_name,
        cpu_cores_logical=logical,
        cpu_cores_physical=physical,
        total_ram_gb=total_ram_gb,
        gpu_vendor="none",
        gpu_name="CPU only",
        gpu_vram_gb=0.0,
        unified_memory=False,
    )
