import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

class CopybookResolver:
    """
    Locates and parses COPYBOOK files (.cpy, .cbl, .cob) from project directories.
    Tracks resolved vs unresolved copybook dependencies.
    """
    def __init__(self, search_paths: List[Path]):
        self.search_paths = search_paths
        self.resolved_cache: Dict[str, Tuple[Path, str]] = {}
        self.unresolved: List[str] = []

    def resolve(self, copybook_name: str) -> Optional[Tuple[Path, str]]:
        raw_name = copybook_name.strip("'\"")
        # Protect against directory traversal attacks
        clean_name = Path(raw_name).name
        if not clean_name:
            return None

        # Check standard extensions: no extension, .cpy, .CPY, .cbl, .CBL, .cob, .COB
        candidate_names = [
            clean_name,
            f"{clean_name}.cpy",
            f"{clean_name}.CPY",
            f"{clean_name}.cbl",
            f"{clean_name}.CBL",
            f"{clean_name}.cob",
            f"{clean_name}.COB",
            clean_name.lower(),
            f"{clean_name.lower()}.cpy",
            clean_name.upper(),
            f"{clean_name.upper()}.CPY"
        ]

        for p in self.search_paths:
            base_dir = p.resolve()
            for cand in candidate_names:
                candidate_path = (p / cand).resolve()
                try:
                    candidate_path.relative_to(base_dir)
                except ValueError:
                    # Target path is outside base_dir
                    continue

                if candidate_path.exists() and candidate_path.is_file():
                    with open(candidate_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    self.resolved_cache[clean_name] = (candidate_path, content)
                    return candidate_path, content

        if clean_name not in self.unresolved:
            self.unresolved.append(clean_name)
        return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "resolved": list(self.resolved_cache.keys()),
            "unresolved": self.unresolved
        }
