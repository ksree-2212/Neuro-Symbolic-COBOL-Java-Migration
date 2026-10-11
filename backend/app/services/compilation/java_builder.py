import os
from pathlib import Path
from typing import List, Dict, Any
from backend.app.schemas.migration import GeneratedFile

class JavaProjectBuilder:
    """
    Constructs a standard Maven-compatible Java project layout.
    """
    @staticmethod
    def build_maven_pom(artifact_id: str = "migrated-app", java_version: str = "17") -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.migration</groupId>
    <artifactId>{artifact_id.lower()}</artifactId>
    <version>1.0.0-SNAPSHOT</version>

    <properties>
        <maven.compiler.source>{java_version}</maven.compiler.source>
        <maven.compiler.target>{java_version}</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-api</artifactId>
            <version>5.9.2</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-engine</artifactId>
            <version>5.9.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
</project>
"""

    @classmethod
    def assemble_project(cls, output_dir: Path, files: List[GeneratedFile], entry_point: str) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        src_main_java = output_dir / "src" / "main" / "java" / "com" / "migration"
        src_test_java = output_dir / "src" / "test" / "java" / "com" / "migration"
        src_main_java.mkdir(parents=True, exist_ok=True)
        src_test_java.mkdir(parents=True, exist_ok=True)

        # Write pom.xml
        pom_path = output_dir / "pom.xml"
        with open(pom_path, "w", encoding="utf-8") as f:
            f.write(cls.build_maven_pom(artifact_id=entry_point))

        # Write source files
        for gf in files:
            file_name = Path(gf.path).name
            target_path = src_main_java / file_name
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(gf.content)

        return output_dir
