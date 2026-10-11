import os
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from backend.app.config import settings

import shutil
from backend.app.services.compilation.toolchain import JavaToolchainDetector

class JavaRunner:
    """
    Executes compiled or source-level Java code with isolated test inputs.
    Parses Java stdout into structured output and records runtime metrics.
    Gracefully handles missing Java 17 toolchain.
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

    def execute(self, project_dir: Path, class_name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.java_bin or (not Path(self.java_bin).exists() and not shutil.which(self.java_bin)):
            return {
                "status": "ERROR",
                "error_type": "TOOLCHAIN_UNAVAILABLE",
                "message": f"Java 17 JDK is not available on this host: {self.toolchain.status_message}"
            }

        target_source = project_dir / "src" / "main" / "java" / "com" / "migration" / f"{class_name}.java"
        if not target_source.exists():
            return {
                "status": "ERROR",
                "error_type": "MISSING_SOURCE_FILE",
                "message": f"Source file not found: {target_source}"
            }

        # Build execution arguments
        args = [f"{k}={v}" for k, v in input_data.items()]
        cmd = [self.java_bin, str(target_source)] + args

        start_time = time.time()
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(project_dir)
            )
            exec_time_ms = (time.time() - start_time) * 1000.0

            if res.returncode != 0:
                return {
                    "status": "ERROR",
                    "error_type": "RUNTIME_ERROR",
                    "stderr": res.stderr,
                    "stdout": res.stdout,
                    "execution_time_ms": exec_time_ms
                }

            stdout = res.stdout
            if "___RESULT_JSON___" in stdout:
                json_part = stdout.split("___RESULT_JSON___", 1)[1].strip()
                try:
                    data = json.loads(json_part)
                    data["execution_time_ms"] = exec_time_ms
                    return data
                except json.JSONDecodeError:
                    return {
                        "status": "ERROR",
                        "error_type": "OUTPUT_PARSE_ERROR",
                        "raw_output": json_part,
                        "execution_time_ms": exec_time_ms
                    }

            return {
                "status": "OK",
                "raw_stdout": stdout,
                "execution_time_ms": exec_time_ms
            }

        except subprocess.TimeoutExpired:
            return {
                "status": "ERROR",
                "error_type": "TIMEOUT",
                "message": "Java execution timed out after 15 seconds."
            }
        except FileNotFoundError:
            return {
                "status": "ERROR",
                "error_type": "TOOLCHAIN_UNAVAILABLE",
                "message": f"Java executable not found ({self.java_bin}). Java 17 JDK is required."
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "error_type": "EXECUTION_EXCEPTION",
                "message": str(e)
            }
