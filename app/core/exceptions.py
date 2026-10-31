class AssistantError(Exception):
    """Базовая ошибка пайплайна ассистента."""


class ConfigurationError(AssistantError):
    """Не заданы нужные настройки или нет локальных ресурсов."""


class NotFoundError(AssistantError):
    """Записи нет или она принадлежит другому пользователю."""


class TranscriptionError(AssistantError):
    """Аудио не удалось конвертировать или распознать."""


class SpeechSynthesisError(AssistantError):
    """Бэкенд синтеза речи упал."""


class LLMError(AssistantError):
    """Вызов чат-модели упал или вернул негодный ответ."""


class ExternalServiceError(AssistantError):
    def __init__(self, service: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service
        self.status_code = status_code
