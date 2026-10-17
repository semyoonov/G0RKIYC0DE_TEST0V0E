class AssistantError(Exception):
    """Base error of the assistant pipeline."""


class ConfigurationError(AssistantError):
    """Required settings or local resources are missing."""


class EventValidationError(AssistantError):
    """User intent cannot be mapped to a valid event."""


class NotFoundError(AssistantError):
    """Requested entity does not exist or belongs to another user."""


class TranscriptionError(AssistantError):
    """Audio cannot be converted or recognised."""


class SpeechSynthesisError(AssistantError):
    """Text-to-speech backend failed."""


class LLMError(AssistantError):
    """Chat model call failed or returned an unusable answer."""


class ToolExecutionError(AssistantError):
    """A tool call from the model cannot be executed."""


class ExternalServiceError(AssistantError):
    def __init__(self, service: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service
        self.status_code = status_code
