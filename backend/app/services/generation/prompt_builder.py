from typing import List, Dict, Any, Optional
from backend.app.schemas.ast_graph import ChunkInfo
from backend.app.services.retrieval.hybrid_retriever import ContextBundle

class TranslationPromptBuilder:
    """
    Builds rich, structure-aware migration prompts adhering to Section 20 of requirements.
    """
    @staticmethod
    def build_prompt(
        project_name: str,
        target_name: str,
        context: ContextBundle,
        repair_context: Optional[Dict[str, Any]] = None,
        baseline: bool = False
    ) -> str:
        prompt_parts = []

        if baseline:
            prompt_parts.append("=== BASELINE UNCONSTRAINED MIGRATION ===")
            prompt_parts.append("Translate the following COBOL code to Java. Return a functional Java project.")
            prompt_parts.append("\n### SOURCE CHUNKS:")
            for chk in context.primary_chunks:
                prompt_parts.append(f"```cobol\n{chk.source_code}\n```")
            return "\n".join(prompt_parts)

        # Proposed AST-Guided Neuro-Symbolic Prompt
        prompt_parts.append(f"=== COBOL TO JAVA MIGRATION TASK: {target_name} (Project: {project_name}) ===")
        prompt_parts.append(
            "You are an expert compiler and legacy modernization engineer. "
            "Translate the following COBOL program into a clean, modern, and verifiable Java class."
        )

        # 1. Primary Source Chunks
        prompt_parts.append("\n### 1. PRIMARY TARGET CODE CHUNKS (Retrieved via Semantic Vector Memory):")
        for chk in context.primary_chunks:
            prompt_parts.append(f"// Symbol: {chk.symbol_name} ({chk.symbol_type}) [Lines {chk.start_line}-{chk.end_line}]")
            prompt_parts.append(f"```cobol\n{chk.source_code}\n```\n")

        # 2. Dependency Chunks
        if context.dependency_chunks:
            prompt_parts.append("\n### 2. REQUIRED DEPENDENCY CHUNKS (Retrieved via Graph Memory Expansion):")
            for chk in context.dependency_chunks:
                prompt_parts.append(f"// Dependency Symbol: {chk.symbol_name} ({chk.symbol_type})")
                prompt_parts.append(f"```cobol\n{chk.source_code}\n```\n")

        # 3. Copybooks
        if context.copybooks:
            prompt_parts.append("\n### 3. RESOLVED COPYBOOK DEFINITIONS:")
            for cb in context.copybooks:
                prompt_parts.append(f"// Copybook: {cb['name']}")
                prompt_parts.append(f"```cobol\n{cb['content']}\n```\n")

        # 4. Structural Constraints
        if context.structural_constraints:
            prompt_parts.append("\n### 4. DETERMINISTIC STRUCTURAL CONSTRAINTS:")
            for sc in context.structural_constraints:
                prompt_parts.append(f"- {sc}")

        # 5. Translation & Verification Rules
        prompt_parts.append("\n### 5. TARGET JAVA REQUIREMENTS:")
        prompt_parts.append("- Use package: `package com.migration;`")
        prompt_parts.append("- Use `java.math.BigDecimal` with RoundingMode.HALF_UP for fixed-point decimal arithmetic.")
        prompt_parts.append("- Implement a `public Map<String, Object> execute(Map<String, Object> input)` method for testability.")
        prompt_parts.append("- Preserve exact calculation order and conditional branching.")
        prompt_parts.append("- Provide a standard `main(String[] args)` method.")
        prompt_parts.append("- Never invent missing dependencies or omit unsupported constructs silently.")

        # 6. Repair feedback if applicable
        if repair_context:
            prompt_parts.append("\n### 6. PREVIOUS ATTEMPT FAILURE INFORMATION (REPAIR REQUIRED):")
            prompt_parts.append(f"Attempt #{repair_context.get('attempt_number', 1)} failed verification.")
            if repair_context.get("compile_errors"):
                prompt_parts.append(f"Compiler Error:\n{repair_context['compile_errors']}")
            if repair_context.get("failing_tests"):
                prompt_parts.append("Failing Test Cases:")
                for ft in repair_context["failing_tests"][:5]:
                    prompt_parts.append(f"  Input: {ft.get('input')} | Expected: {ft.get('expected')} | Actual: {ft.get('actual')}")
            prompt_parts.append("Fix the Java implementation to resolve these errors while preserving previously verified behavior.")

        # 7. Output Format
        prompt_parts.append("\n### 7. OUTPUT FORMAT:")
        prompt_parts.append(
            "Respond ONLY with a valid JSON object matching this schema (enclosed in ```json ... ```):\n"
            "{\n"
            '  "files": [\n'
            '    {\n'
            '      "path": "ClassName.java",\n'
            '      "content": "..."\n'
            '    }\n'
            '  ],\n'
            '  "entry_point": "ClassName",\n'
            '  "notes": ["..."],\n'
            '  "unsupported_constructs": []\n'
            "}"
        )

        return "\n".join(prompt_parts)
