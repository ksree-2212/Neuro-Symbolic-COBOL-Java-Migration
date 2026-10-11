import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from backend.app.config import settings

from backend.app.services.compilation.toolchain import JavaToolchainDetector, JavaToolchainStatus

@dataclass
class CompileResult:
    success: bool
    errors: str
    warnings: str
    error_lines: List[int]
    error_type: Optional[str] = None

class JavaCompiler:
    """
    Executes Java compilation checks on generated project files using Java 17 toolchain.
    Captures compiler diagnostics, line numbers, and error classifications.
    Provides graceful fallback when Java 17 JDK is unavailable.
    """
    def __init__(self, java_home: Optional[str] = None):
        self.toolchain = JavaToolchainDetector.detect()
        if java_home:
            if Path(java_home).exists():
                candidates = [Path(java_home)]
                self.java_bin = JavaToolchainDetector._find_executable("java", candidates) or (
                    str(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
                )
            else:
                self.java_bin = str(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
        else:
            self.java_bin = self.toolchain.java_bin

    def compile(self, project_dir: Path, entry_file: Path) -> CompileResult:
        if not self.java_bin or (not Path(self.java_bin).exists() and not shutil.which(self.java_bin)):
            return CompileResult(
                success=False,
                errors=f"Java 17 JDK is not available on this host: {self.toolchain.status_message}",
                warnings="TOOLCHAIN_UNAVAILABLE",
                error_lines=[],
                error_type="TOOLCHAIN_UNAVAILABLE"
            )

        if not entry_file.exists():
            return CompileResult(
                success=False,
                errors=f"Entry file not found: {entry_file}",
                warnings="",
                error_lines=[],
                error_type="MISSING_FILE"
            )

        cmd = [self.java_bin, str(entry_file)]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
                cwd=str(project_dir)
            )

            combined_output = (res.stderr + "\n" + res.stdout).strip()

            # Note: Java 17 single-file source runner prints "error: can't find main(String[]) method"
            # ONLY AFTER compilation successfully passes!
            if "can't find main(String[]) method" in combined_output and "error: compilation failed" not in combined_output:
                return CompileResult(
                    success=True,
                    errors="",
                    warnings=combined_output,
                    error_lines=[],
                    error_type=None
                )

            # Check if compilation failed
            if "error: compilation failed" in combined_output or (": error:" in combined_output):
                error_lines = []
                for match in re.finditer(r':(\d+):\s*error:', combined_output):
                    error_lines.append(int(match.group(1)))

                err_type = "SYNTAX_ERROR"
                if "cannot find symbol" in combined_output:
                    err_type = "MISSING_SYMBOL"
                elif "incompatible types" in combined_output:
                    err_type = "TYPE_ERROR"
                elif "package does not exist" in combined_output:
                    err_type = "MISSING_IMPORT"

                return CompileResult(
                    success=False,
                    errors=combined_output,
                    warnings="",
                    error_lines=error_lines,
                    error_type=err_type
                )

            return CompileResult(
                success=True,
                errors="",
                warnings="",
                error_lines=[],
                error_type=None
            )

        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                errors="Compilation timed out after 20 seconds.",
                warnings="",
                error_lines=[],
                error_type="TIMEOUT"
            )
        except FileNotFoundError:
            return CompileResult(
                success=False,
                errors=f"Java executable not found ({self.java_bin}). Java 17 JDK is required.",
                warnings="TOOLCHAIN_UNAVAILABLE",
                error_lines=[],
                error_type="TOOLCHAIN_UNAVAILABLE"
            )
        except Exception as e:
            return CompileResult(
                success=False,
                errors=f"Execution error: {str(e)}",
                warnings="",
                error_lines=[],
                error_type="RUNTIME_ERROR"
            )
