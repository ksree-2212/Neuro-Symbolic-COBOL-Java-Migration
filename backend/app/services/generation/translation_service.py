import re
import json
import logging
from typing import Dict, Any, Optional, List
from backend.app.config import settings
from backend.app.providers.base import LLMProvider, LLMResponse
from backend.app.providers.openai_provider import OpenAICompatibleProvider
from backend.app.providers.anthropic_provider import AnthropicProvider
from backend.app.providers.local_provider import LocalModelProvider
from backend.app.schemas.migration import GeneratedFile

logger = logging.getLogger(__name__)

class TranslationService:
    """
    Orchestrates COBOL -> Java code translation using configurable LLM providers.
    Parses and sanitizes LLM output into concrete project files.
    """
    def __init__(self, provider: Optional[LLMProvider] = None):
        if provider:
            self.provider = provider
        else:
            p_name = settings.llm_provider.lower()
            if p_name in ('openai', 'azure', 'vllm') and settings.llm_api_key:
                self.provider = OpenAICompatibleProvider()
            elif p_name in ('anthropic', 'claude') and settings.llm_api_key:
                self.provider = AnthropicProvider()
            else:
                self.provider = LocalModelProvider()

    def translate(self, prompt: str) -> Dict[str, Any]:
        response: LLMResponse = self.provider.generate(prompt)
        raw_text = response.content.strip()

        # Extract JSON from markdown fences if present
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_text)
        json_str = json_match.group(1).strip() if json_match else raw_text

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Fallback: attempt to find raw JSON object
            start = raw_text.find('{')
            end = raw_text.rfind('}')
            if start != -1 and end != -1:
                try:
                    data = json.loads(raw_text[start:end+1])
                except:
                    data = self._salvage_code_as_file(raw_text)
            else:
                data = self._salvage_code_as_file(raw_text)

        # Standardize files list
        files = []
        for f in data.get("files", []):
            files.append(GeneratedFile(
                path=f.get("path", "MigratedProgram.java"),
                content=f.get("content", "")
            ))

        return {
            "files": files,
            "entry_point": data.get("entry_point", "MigratedProgram"),
            "notes": data.get("notes", []),
            "unsupported_constructs": data.get("unsupported_constructs", []),
            "model": response.model,
            "tokens": response.completion_tokens
        }

    def _salvage_code_as_file(self, raw_text: str) -> Dict[str, Any]:
        # If model returned direct Java code
        java_match = re.search(r'```(?:java)?\s*([\s\S]*?)```', raw_text)
        code = java_match.group(1).strip() if java_match else raw_text
        m = re.search(r'public\s+class\s+([A-Za-z0-9_]+)', code)
        class_name = m.group(1) if m else "MigratedProgram"
        return {
            "files": [{"path": f"{class_name}.java", "content": code}],
            "entry_point": class_name,
            "notes": ["Extracted from raw response."],
            "unsupported_constructs": []
        }
