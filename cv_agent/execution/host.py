"""
cv_agent.execution.host — HostProfile, HostRequirement, HostVerifier.

Cross-cutting execution concern: verifying that the current host satisfies a
job's declared requirements before any platform-sensitive command is attempted
(docs/APPROVALS.md "Platform-sensitive actions" rule; ADR-0013 §3.3).

Placed here rather than in cv_agent.execution.jobs.host so that future
callers outside the job boundary (e.g. a platform-check CLI command) can
import it without depending on the jobs subpackage.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HostProfile:
    """What was detected about the current execution host at verification time."""

    os: str
    """Normalised OS family: "linux", "darwin", "windows", or the raw
    platform.system().lower() value for anything else."""
    gpu_available: bool
    gpu_vendor: str | None
    """Lower-case vendor string ("nvidia", "amd", …) or None if no GPU
    was detected."""
    driver_version: str | None
    """Reported driver version string, or None if not detected."""


@dataclass(frozen=True)
class HostRequirement:
    """What a job declares it needs from the host. None = unspecified/any."""

    os: str
    """Required OS family string, e.g. "linux". Compared case-insensitively
    against HostProfile.os."""
    gpu_vendor: str | None = None
    """Required GPU vendor lower-case string, e.g. "nvidia". None = CPU-only
    or any GPU acceptable."""
    min_vram_mb: int | None = None
    """Minimum VRAM in MB. None = unspecified."""


class HostVerifier(Protocol):
    """
    Checks that the current execution host satisfies a job's HostRequirement.

    Called by JobExecutor.start_job() before runtime.start() is called.
    Never raises — verification failure is returned as (False, reason).
    """

    def verify(self, requirement: HostRequirement) -> tuple[bool, str]:
        """
        Returns (True, "") if the current host satisfies `requirement`,
        or (False, human-readable reason) if it does not.
        Never raises; a detection failure counts as unsatisfied.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete verifier: Linux + NVIDIA GPU (D-044)
# ---------------------------------------------------------------------------

def _detect_host_profile() -> HostProfile:
    """
    Detect the current host. Never raises — detection failure yields
    conservative (gpu_available=False) values.
    """
    os_name = platform.system().lower()
    # Normalise to the three common families; leave anything else as-is.
    if os_name == "linux":
        pass
    elif os_name == "darwin":
        pass
    elif os_name == "windows":
        pass

    gpu_available = False
    gpu_vendor: str | None = None
    driver_version: str | None = None

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            raw = result.stdout.strip()
            if raw:
                gpu_available = True
                gpu_vendor = "nvidia"
                driver_version = raw.splitlines()[0].strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return HostProfile(
        os=os_name,
        gpu_available=gpu_available,
        gpu_vendor=gpu_vendor,
        driver_version=driver_version,
    )


class LinuxNvidiaHostVerifier:
    """
    Concrete HostVerifier for the D-044 execution class: Linux + NVIDIA GPU.

    Calls `nvidia-smi` to confirm GPU presence. Does not name or require a
    specific physical machine — any Linux host with an NVIDIA GPU and driver
    satisfies the check.

    Deterministic and testable: callers may inject a HostProfile directly
    via the constructor to bypass subprocess detection in unit tests.
    """

    def __init__(self, profile: HostProfile | None = None) -> None:
        self._profile = profile

    def _get_profile(self) -> HostProfile:
        if self._profile is not None:
            return self._profile
        return _detect_host_profile()

    def verify(self, requirement: HostRequirement) -> tuple[bool, str]:
        """
        Returns (True, "") when the host satisfies `requirement`,
        or (False, reason) when it does not.
        Never raises.
        """
        try:
            profile = self._get_profile()
        except Exception as exc:  # noqa: BLE001
            return False, f"Host detection failed: {exc}"

        if profile.os != requirement.os.lower():
            return (
                False,
                f"Host OS is '{profile.os}'; job requires '{requirement.os.lower()}'.",
            )

        if requirement.gpu_vendor is not None:
            if not profile.gpu_available or profile.gpu_vendor != requirement.gpu_vendor.lower():
                detected = f"'{profile.gpu_vendor}'" if profile.gpu_vendor else "none"
                return (
                    False,
                    f"Host GPU vendor is {detected}; "
                    f"job requires '{requirement.gpu_vendor.lower()}'.",
                )

        if requirement.min_vram_mb is not None:
            if not profile.gpu_available:
                return False, "Job requires minimum VRAM but no GPU is available."
            # VRAM measurement is not yet implemented; fail closed rather than
            # pass a requirement we cannot verify.
            return (
                False,
                f"Job requires {requirement.min_vram_mb} MB VRAM but VRAM "
                "measurement is not yet implemented; cannot verify the "
                "requirement. (V1 limitation — fail closed per ADR-0013 §3.3.)",
            )

        return True, ""
