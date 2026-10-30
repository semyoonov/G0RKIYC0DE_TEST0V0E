from __future__ import annotations

import httpx

from app.core.config import Settings


class EmailDeliveryError(RuntimeError):
    """The email provider could not accept the verification message."""


class EmailSender:
    """Minimal Resend API client. It sends only transactional login codes."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.resend_api_key.strip()
        self._from = settings.email_from.strip()
        self._ttl_minutes = max(1, (settings.email_code_ttl_seconds + 59) // 60)

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._from)

    async def send_login_code(self, email: str, code: str) -> None:
        if not self.configured:
            raise EmailDeliveryError("Email sending is not configured; set RESEND_API_KEY and EMAIL_FROM")

        payload = {
            "from": self._from,
            "to": [email],
            "subject": "Код входа в GorkyCode",
            "text": (
                f"Ваш код входа в GorkyCode: {code}\n\n"
                f"Код действует {self._ttl_minutes} мин. Если вы не запрашивали вход, "
                "просто проигнорируйте письмо."
            ),
            "html": (
                "<p>Ваш код входа в GorkyCode:</p>"
                f"<p style='font-size:28px;font-weight:700;letter-spacing:6px'>{code}</p>"
                f"<p>Код действует {self._ttl_minutes} мин. Если вы не запрашивали вход, "
                "просто проигнорируйте письмо.</p>"
            ),
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
                response.raise_for_status()
        except (httpx.HTTPError, ValueError) as error:
            raise EmailDeliveryError("Email provider rejected the verification message") from error
