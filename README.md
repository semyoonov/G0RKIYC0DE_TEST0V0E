# Архитектура проекта: Голосовой ассистент для задач и встреч

Проект: Голосовой ассистент (монолит на Python).
Все файлы в репозитории подготовлены как пустые заготовки для командной разработки.
Ниже приведено описание архитектуры, стека и зон ответственности каждого участника.

---

## 🛠 Выбранный стек технологий
- **Архитектура:** Монолит
- **Язык:** Python
- **Распознавание речи (STT):** Vosk (офлайн)
- **Синтез речи (TTS):** Sber SaluteSpeech API
- **Нейросеть (LLM):** GigaChat API (с вызовом тулзов / Function Calling)
- **База данных:** PostgreSQL
- **ORM & Миграции:** SQLAlchemy + Alembic
- **Кэш:** Redis (кэширование основных запросов)
- **Интерфейсы:**
  - Telegram-бот
  - Бот в MAX
  - Веб-интерфейс

---

## 👥 Распределение задач

### 1. AI, Голос и LLM
**Участники:** `@FreezeEngine`, `@semyoonov`, `@IGapone`
**Задачи:**
- Распознавание речи через Vosk (конвертация любого аудио формата в 16кГц WAV и транскрибация).
- Синтез речи через API Сбера (SaluteSpeech).
- Интеграция с GigaChat по API:
  - Системный промпт с передачей текущей даты, времени и дня недели (для обработки «завтра», «в пятницу»).
  - Описание схем тулзов (function calling): `create_task`, `create_meeting`, `list_events`, `search_events`.
  - Уточняющий диалог, если не хватает данных (например: «Поставь встречу с Иваном завтра» -> «На какое время поставить встречу?»).
- Оркестратор пайплайна: аудио/текст -> распознавание -> запрос в LLM -> вызов тулзов -> синтез речи -> ответ.

**Папки и файлы для работы:**
- `app/ai/stt/vosk_stt.py` — загрузка модели Vosk и распознавание речи.
- `app/ai/stt/audio_converter.py` — конвертер аудио (из Telegram OGG Opus / WebM браузера в 16кГц WAV).
- `app/ai/tts/sber_tts.py` — клиент синтеза речи SaluteSpeech.
- `app/ai/llm/gigachat_client.py` — клиент к API GigaChat.
- `app/ai/llm/prompts.py` — системные промпты и контекст времени.
- `app/ai/llm/tools.py` — описание схемы функций (tool calls) для GigaChat.
- `app/ai/llm/tool_executor.py` — обработчик выполнения тулзов (связка с репозиториями).
- `app/ai/assistant.py` — главный сервис ассистента, объединяющий все этапы.

---

### 2. База данных, Репозитории, Redis и Шедулер
**Участник:** `@werenotgonnafall`
**Задачи:**
- Проектирование схемы БД PostgreSQL и SQLAlchemy моделей:
  - Пользователи (`User`).
  - Записи (`Event`): тип (задача / встреча / напоминание), название/текст, дата и время, дата создания, статус выполнения (выполнено / не выполнено).
- Настройка миграций через Alembic.
- Репозитории:
  - CRUD операций.
  - Выборка задач и встреч за указанный период (сегодня, завтра, неделя).
  - Поиск ранее созданных задач и встреч по естественному запросу (поиск по названию и описанию).
- Интеграция Redis для кэширования частых запросов.
- Шедулер (напоминания по времени).

**Папки и файлы для работы:**
- `app/db/base.py` — базовый класс моделей SQLAlchemy (DeclarativeBase).
- `app/db/session.py` — создание engine и async_sessionmaker для PostgreSQL.
- `app/db/models/user.py` — модель пользователя в БД.
- `app/db/models/event.py` — модель задачи, встречи, напоминания.
- `app/repositories/base.py` — базовый класс репозитория.
- `app/repositories/user_repository.py` — репозиторий для пользователей.
- `app/repositories/event_repository.py` — методы создания, фильтрации по датам и поиска по событиям.
- `app/services/cache/redis_service.py` — клиент Redis и логика кэширования.
- `app/services/scheduler/reminder_service.py` — планировщик для проверки и отправки напоминаний.
- `alembic/` и `alembic.ini` — миграции базы данных.

---

### 3. Бот в MAX и Веб-интерфейс
**Участник:** `@ABathingDanil`
**Задачи:**
- Создание бота для мессенджера MAX:
  - Клиент API MAX, обработка входящих текстовых и голосовых сообщений.
  - Передача запросов в общий пайплайн ассистента и возврат ответа (текст / голос).
- Веб-интерфейс:
  - Бэкенд на FastAPI: роуты для приема текста и аудиофайлов.
  - Минималистичная фронтенд-страница: кнопка записи с микрофона, история диалога, воспроизведение ответа ассистента.

**Папки и файлы для работы:**
- `app/interfaces/max/bot.py` — клиент и запуск бота в MAX.
- `app/interfaces/max/handlers.py` — обработчики сообщений для MAX.
- `app/interfaces/web/app.py` — инициализация FastAPI.
- `app/interfaces/web/routes.py` — эндпоинты `/api/chat`, `/api/voice` и др.
- `app/interfaces/web/templates/index.html` — HTML страница чата и кнопки записи.
- `app/interfaces/web/static/css/style.css` — стили веб-интерфейса.
- `app/interfaces/web/static/js/app.js` — захват аудио с микрофона (MediaRecorder) и отправка на сервер.

---

### 4. Телеграм-бот
**Участник:** `@artemflichendery`
**Задачи:**
- Разработка Telegram-бота на `aiogram 3`.
- Обработка текстовых команд и свободных сообщений.
- Обработка голосовых сообщений:
  - Скачивание аудиофайла `.ogg`.
  - Передача в `VoiceAssistantService`.
  - Отправка текстового ответа и сгенерированного голосового ответа обратно пользователю.
- Кнопки быстрого доступа (например, «Что у меня сегодня?», «Задачи на завтра»).

**Папки и файлы для работы:**
- `app/interfaces/telegram/bot.py` — создание экземпляра бота и Dispatcher.
- `app/interfaces/telegram/keyboards.py` — клавиатуры и меню.
- `app/interfaces/telegram/handlers/common.py` — команды `/start`, `/help`.
- `app/interfaces/telegram/handlers/text.py` — хэндлер текстовых сообщений.
- `app/interfaces/telegram/handlers/voice.py` — хэндлер голосовых сообщений.

---

## 🗂 Полное дерево файлов проекта

```text
gorkycode_testovoe/
├── .env.example                     # Шаблон переменных окружения
├── .gitignore                       # Игнорируемые файлы (git)
├── alembic.ini                      # Настройки Alembic
├── docker-compose.yml               # Описание сервисов PostgreSQL, Redis, App
├── Dockerfile                       # Сборка контейнера приложения
├── main.py                          # Главная точка входа монолита
├── requirements.txt                 # Список зависимостей проекта
├── README.md                        # Этот файл с описанием архитектуры и задач
│
├── alembic/                         # Миграции БД
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── .gitkeep
│
├── models/                          # Папка для скачивания модели Vosk
│   └── .gitkeep
│
└── app/
    ├── __init__.py
    │
    ├── core/                        # Базовая конфигурация
    │   ├── __init__.py
    │   ├── config.py                # Pydantic Settings (.env)
    │   ├── logger.py                # Настройка логирования
    │   └── exceptions.py            # Кастомные исключения
    │
    ├── domain/                      # Общие схемы и структуры данных (Pydantic)
    │   ├── __init__.py
    │   ├── enums.py                 # Enums: EventType, EventStatus
    │   └── models.py                # DTO: EventCreate, EventRead, AssistantRequest/Response
    │
    ├── db/                          # [Ответственный: @werenotgonnafall]
    │   ├── __init__.py
    │   ├── base.py                  # Базовый DeclarativeBase
    │   ├── session.py               # Подключение к PostgreSQL и async session
    │   └── models/
    │       ├── __init__.py
    │       ├── user.py              # ORM модель пользователя
    │       └── event.py             # ORM модель задачи, встречи, напоминания
    │
    ├── repositories/                # [Ответственный: @werenotgonnafall]
    │   ├── __init__.py
    │   ├── base.py                  # Базовый интерфейс репозитория
    │   ├── user_repository.py       # Репозиторий пользователей
    │   └── event_repository.py      # Выборка по датам (сегодня/завтра/неделя) и поиск
    │
    ├── services/                    # [Ответственный: @werenotgonnafall]
    │   ├── __init__.py
    │   ├── cache/
    │   │   ├── __init__.py
    │   │   └── redis_service.py     # Кэширование запросов в Redis
    │   └── scheduler/
    │       ├── __init__.py
    │       └── reminder_service.py  # Планировщик отправки напоминаний
    │
    ├── ai/                          # [Ответственные: @FreezeEngine, @semyoonov, @IGapone]
    │   ├── __init__.py
    │   ├── assistant.py             # Главный оркестратор ассистента
    │   ├── stt/
    │   │   ├── __init__.py
    │   │   ├── vosk_stt.py          # Распознавание речи через Vosk
    │   │   └── audio_converter.py   # Конвертер аудиофайлов (OGG/WebM -> WAV 16кГц)
    │   ├── tts/
    │   │   ├── __init__.py
    │   │   └── sber_tts.py          # Синтез речи через SaluteSpeech API
    │   └── llm/
    │       ├── __init__.py
    │       ├── gigachat_client.py   # Клиент API GigaChat
    │       ├── prompts.py           # Системные промпты с контекстом даты и времени
    │       ├── tools.py             # Схемы тулзов (создание, поиск, список)
    │       └── tool_executor.py     # Исполнитель тулзов над репозиториями
    │
    └── interfaces/                  # Клиентские интерфейсы
        ├── __init__.py
        ├── telegram/                # [Ответственный: @artemflichendery]
        │   ├── __init__.py
        │   ├── bot.py               # Инициализация бота и диспетчера
        │   ├── keyboards.py         # Клавиатуры Telegram
        │   └── handlers/
        │       ├── __init__.py
        │       ├── common.py        # /start, /help
        │       ├── text.py          # Текстовые сообщения
        │       └── voice.py         # Голосовые сообщения
        ├── max/                     # [Ответственный: @ABathingDanil]
        │   ├── __init__.py
        │   ├── bot.py               # Бот в MAX
        │   └── handlers.py          # Обработчики сообщений для MAX
        └── web/                     # [Ответственный: @ABathingDanil]
            ├── __init__.py
            ├── app.py               # FastAPI приложение
            ├── routes.py            # Роуты веб-интерфейса
            ├── static/
            │   ├── css/style.css    # Стили
            │   └── js/app.js        # Запись с микрофона и аудио-плеер
            └── templates/
                └── index.html       # HTML страница чата
```
