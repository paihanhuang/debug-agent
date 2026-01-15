"""LLM client for entity and relation extraction."""

from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """Response from an LLM."""
    content: str
    model: str
    usage: dict[str, int] | None = None
    raw_response: Any = None


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""
    
    @abstractmethod
    def complete(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        """Generate a completion for the given prompt."""
        pass
    
    @abstractmethod
    def complete_json(
        self, 
        prompt: str, 
        system_prompt: str | None = None
    ) -> dict[str, Any]:
        """Generate a JSON completion."""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI API client."""
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
        temperature: float = 0.1,
    ):
        """Initialize OpenAI client.
        
        Args:
            api_key: OpenAI API key. Defaults to OPENAI_API_KEY env var.
            model: Model to use.
            temperature: Sampling temperature.
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai")
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
    
    def complete(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        """Generate a completion."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )
        
        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=self.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            raw_response=response,
        )
    
    def complete_json(
        self, 
        prompt: str, 
        system_prompt: str | None = None
    ) -> dict[str, Any]:
        """Generate a JSON completion."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


class AnthropicClient(BaseLLMClient):
    """Anthropic API client."""
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.1,
    ):
        """Initialize Anthropic client.
        
        Args:
            api_key: Anthropic API key. Defaults to ANTHROPIC_API_KEY env var.
            model: Model to use.
            temperature: Sampling temperature.
        """
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic")
        
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key.")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
    
    def complete(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        """Generate a completion."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        
        response = self.client.messages.create(**kwargs)
        
        content = ""
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
        
        return LLMResponse(
            content=content,
            model=self.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
            raw_response=response,
        )
    
    def complete_json(
        self, 
        prompt: str, 
        system_prompt: str | None = None
    ) -> dict[str, Any]:
        """Generate a JSON completion."""
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no additional text."
        response = self.complete(json_prompt, system_prompt)
        
        # Extract JSON from response
        content = response.content.strip()
        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else content
        
        return json.loads(content)


class LLMClient:
    """Unified LLM client factory."""
    
    @staticmethod
    def create(
        provider: str = "openai",
        **kwargs,
    ) -> BaseLLMClient:
        """Create an LLM client.
        
        Args:
            provider: "openai" or "anthropic"
            **kwargs: Provider-specific arguments.
            
        Returns:
            An LLM client instance.
        """
        if provider.lower() == "openai":
            return OpenAIClient(**kwargs)
        elif provider.lower() == "anthropic":
            return AnthropicClient(**kwargs)
        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'openai' or 'anthropic'.")
