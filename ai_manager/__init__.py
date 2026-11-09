"""DoNotStress AI Manager (Phase 2, object-oriented).

Every check-in passes through here before the Logic Manager. The manager
builds the prompt, calls the Gemini API, parses the reply and validates its
schema; it never invents a result.

    GeminiAIManager            the AI Manager (implements AIManagerInterface)
      |- PromptBuilder         prompt from the 11 answers (never the ID or reflection)
      |- TextGenerator         API client interface -> GeminiTextGenerator (live)
      |- ResponseParser        raw text -> JSON object
      |- ResponseValidator     JSON object -> checked fields (AIResponseSchema)
      |- AIErrorClassifier     exceptions -> error codes
      '- RetryPolicy           retries, back-off and model fallback

Each class lives in its own .py file (Coding Requirements).
"""

from .ai_error_classifier import AIErrorClassifier
from .ai_manager_interface import AIManagerInterface
from .ai_processing_error import AIProcessingError
from .ai_response_schema import AIResponseSchema
from .gemini_ai_manager import GeminiAIManager
from .gemini_text_generator import GeminiTextGenerator
from .prompt_builder import PromptBuilder
from .response_parser import ResponseParser
from .response_validator import ResponseValidator
from .retry_policy import RetryPolicy
from .score_verifier import ScoreVerifier
from .text_generator import TextGenerator

__all__ = [
    "AIErrorClassifier",
    "AIManagerInterface",
    "AIProcessingError",
    "AIResponseSchema",
    "GeminiAIManager",
    "GeminiTextGenerator",
    "PromptBuilder",
    "ResponseParser",
    "ResponseValidator",
    "RetryPolicy",
    "ScoreVerifier",
    "TextGenerator",
]
