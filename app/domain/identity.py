from dataclasses import dataclass

from app.domain.enums import PLATFORM_TITLES, Platform


@dataclass(frozen=True, slots=True)
class Identity:
    """Пользователь глазами одной платформы: платформа и её собственный идентификатор."""

    platform: Platform
    external_id: str
    display_name: str | None = None

    @property
    def platform_title(self) -> str:
        return PLATFORM_TITLES.get(self.platform, self.platform.value)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "platform": self.platform.value,
            "platform_title": self.platform_title,
            "external_id": self.external_id,
            "display_name": self.display_name,
        }
