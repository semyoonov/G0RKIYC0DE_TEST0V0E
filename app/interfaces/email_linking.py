from app.domain.identity import Identity
from app.services.auth.service import (
    AuthService,
    EmailAuthError,
    EmailCodeRateLimit,
    EmailDeliveryError,
)


async def request_email_link(auth: AuthService, identity: Identity, email: str) -> str:
    try:
        await auth.request_email_code(email, identity)
    except EmailCodeRateLimit as error:
        return str(error)
    except EmailAuthError as error:
        return str(error)
    except EmailDeliveryError:
        return "Не удалось отправить письмо. Проверьте настройки почты или попробуйте позже."
    return (
        f"Если адрес {email.strip()} корректен, код отправлен на почту.\n"
        "Затем выполните: /emailcode адрес@example.com 123456"
    )


async def confirm_email_link(
    auth: AuthService,
    identity: Identity,
    email: str,
    code: str,
) -> str:
    try:
        await auth.verify_email_code(email, code, identity)
    except EmailAuthError as error:
        return str(error)
    except EmailDeliveryError:
        return "Авторизация по email пока не настроена. Попробуйте позже."
    return (
        "✅ Email подтверждён, аккаунты связаны. Теперь задачи и встречи этого клиента "
        "используют общий аккаунт."
    )
