import os
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from backend.app.config import settings

@dataclass
class JavaToolchainStatus:
    available: bool
    java_bin: Optional[str]
    javac_bin: Optional[str]
    maven_bin: Optional[str]
    java_version: Optional[str]
    major_version: Optional[int]
    is_java_17_compatible: bool
    maven_available: bool
    maven_version: Optional[str]
    status_message: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class JavaToolchainDetector:
    """
    Cross-platform detector for Java JDK (Java 17+) and Apache Maven.
    Handles Windows (.exe / Program Files search), macOS, and Linux locations.
    Provides diagnostic information and graceful fallbacks when the toolchain is absent.
    """
    _cached_status: Optional[JavaToolchainStatus] = None

    @classmethod
    def _search_standard_locations(cls) -> List[Path]:
        candidates: List[Path] = []
        is_windows = os.name == "nt"

        # 1. Configured JAVA_HOME or environment JAVA_HOME
        env_java_home = os.environ.get("JAVA_HOME")
        if env_java_home and Path(env_java_home).exists():
            candidates.append(Path(env_java_home))
        if settings.java_home and Path(settings.java_home).exists():
            candidates.append(Path(settings.java_home))

        # 2. Windows standard installation roots
        if is_windows:
            win_roots = [
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")),
                Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")),
                Path(os.environ.get("LOCALAPPDATA", "C:\\Users")) / "Programs"
            ]
            subdirs = ["Java", "Eclipse Adoptium", "Microsoft", "Amazon Corretto", "Zulu", "BellSoft"]
            for root in win_roots:
                if not root.exists():
                    continue
                for sub in subdirs:
                    vendor_dir = root / sub
                    if vendor_dir.exists() and vendor_dir.is_dir():
                        try:
                            for jdk_dir in vendor_dir.iterdir():
                                if jdk_dir.is_dir() and (jdk_dir / "bin" / "java.exe").exists():
                                    candidates.append(jdk_dir)
                        except (PermissionError, OSError):
                            pass

        # 3. Unix standard roots
        else:
            unix_roots = [
                Path("/usr/lib/jvm"),
                Path("/usr/java"),
                Path("/opt/homebrew/opt"),
                Path("/Library/Java/JavaVirtualMachines")
            ]
            for root in unix_roots:
                if root.exists() and root.is_dir():
                    try:
                        for entry in root.iterdir():
                            # macOS JDKs have Contents/Home/bin/java
                            if (entry / "Contents" / "Home" / "bin" / "java").exists():
                                candidates.append(entry / "Contents" / "Home")
                            elif (entry / "bin" / "java").exists():
                                candidates.append(entry)
                    except (PermissionError, OSError):
                        pass

        return candidates

    @classmethod
    def _find_executable(cls, name: str, candidate_homes: List[Path]) -> Optional[str]:
        is_windows = os.name == "nt"
        ext = ".exe" if is_windows else ""
        target_name = f"{name}{ext}"

        # 1. Check candidate homes first
        for home in candidate_homes:
            bin_path = home / "bin" / target_name
            if bin_path.exists() and os.access(str(bin_path), os.X_OK):
                return str(bin_path.resolve())

        # 2. Check PATH via shutil.which
        which_path = shutil.which(target_name) or shutil.which(name)
        if which_path:
            return str(Path(which_path).resolve())

        return None

    @classmethod
    def _extract_java_version(cls, java_bin: str) -> Tuple[Optional[str], Optional[int]]:
        try:
            res = subprocess.run(
                [java_bin, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # java -version outputs to stderr
            out = res.stderr + "\n" + res.stdout
            # Search for version pattern: version "17.0.2" or version "21.0.1" or "1.8.0"
            m = re.search(r'version\s*["\']([0-9._]+)["\']', out, re.IGNORECASE)
            if m:
                version_str = m.group(1)
                # Parse major version
                if version_str.startswith("1."):
                    major = int(version_str.split(".")[1])
                else:
                    major = int(version_str.split(".")[0])
                return version_str, major
        except Exception:
            pass
        return None, None

    @classmethod
    def _extract_maven_version(cls, maven_bin: str) -> Optional[str]:
        try:
            res = subprocess.run(
                [maven_bin, "-v"],
                capture_output=True,
                text=True,
                timeout=5
            )
            out = res.stdout + "\n" + res.stderr
            m = re.search(r'Apache Maven\s*([0-9._]+)', out, re.IGNORECASE)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    @classmethod
    def detect(cls, refresh: bool = False) -> JavaToolchainStatus:
        if cls._cached_status is not None and not refresh:
            return cls._cached_status

        candidate_homes = cls._search_standard_locations()
        java_bin = cls._find_executable("java", candidate_homes)
        javac_bin = cls._find_executable("javac", candidate_homes)
        maven_bin = cls._find_executable("mvn", candidate_homes)

        java_version = None
        major_version = None
        is_java_17 = False

        if java_bin:
            java_version, major_version = cls._extract_java_version(java_bin)
            if major_version is not None and major_version >= 17:
                is_java_17 = True

        maven_available = maven_bin is not None
        maven_version = cls._extract_maven_version(maven_bin) if maven_bin else None

        # Build status message
        if not java_bin:
            status_msg = "Java runtime is not installed or not in PATH/JAVA_HOME. Offline migration enabled; compilation & differential testing disabled."
            avail = False
        elif not is_java_17:
            status_msg = f"Java detected ({java_version}), but Java 17+ is required. Compilation check may fail."
            avail = False
        else:
            status_msg = f"Java {java_version} detected and verified (JDK 17+ compatible)."
            avail = True

        status = JavaToolchainStatus(
            available=avail,
            java_bin=java_bin,
            javac_bin=javac_bin,
            maven_bin=maven_bin,
            java_version=java_version,
            major_version=major_version,
            is_java_17_compatible=is_java_17,
            maven_available=maven_available,
            maven_version=maven_version,
            status_message=status_msg,
            details={
                "configured_java_home": settings.java_home,
                "os": os.name,
                "candidate_search_paths": [str(p) for p in candidate_homes]
            }
        )

        cls._cached_status = status
        return status

    @classmethod
    def is_available(cls) -> bool:
        return cls.detect().available
