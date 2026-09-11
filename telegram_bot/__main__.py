"""Run the service using APP_HOST and APP_PORT configuration."""

import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.load()
    uvicorn.run(
        "telegram_bot.main:app",
        host=settings.app_host,
        port=settings.app_port,
    )


if __name__ == "__main__":
    main()
