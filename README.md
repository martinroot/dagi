# Dagi Core — минимальное ядро Hermes

Компактный CLI-агент, а не урезанная установка всей платформы. Этот вариант сверён с актуальным upstream `NousResearch/hermes-agent` на коммите [`848fc0a`](https://github.com/NousResearch/hermes-agent/commit/848fc0ad8be766b9dc10fe42bd80b5fc2d45d95c) от 16 октября 2026 года. Код ядра здесь реализован заново по его основным инвариантам, а не скопирован из второго репозитория-ориентира.

## Состав ядра

- Один потоковый OpenAI-compatible API адаптер; OpenAI, OpenRouter и совместимые endpoint задаются конфигурацией.
- Цикл агента: текст → вызов инструмента → результат → продолжение ответа.
- SQLite-транскрипт, FTS5-поиск по прошлым сообщениям и простая библиотека навыков.
- Файловые инструменты в пределах workspace; tool-call записывается в БД до запуска побочного эффекта.
- Терминальный CLI без панели, сервера или TUI-фреймворка.

Нет веб-панели, мессенджер-шлюзов, MCP, cron, voice, multi-agent, профилей и удалённых backend-интеграций. В рантайме одна прямая зависимость: `openai`; SQLite и CLI используют стандартную библиотеку Python.

## Безопасность

`DAGI_ENABLE_SHELL` по умолчанию выключен. При `DAGI_ENABLE_SHELL=1` каждая shell-команда требует отдельного интерактивного подтверждения; отображение команды экранирует управляющие символы. Workspace ограничивает файловые инструменты, но не является OS-level sandbox для shell. База создаётся с правами `0600`; каталог по умолчанию `~/.dagi` — `0700` на POSIX. Если явно задан существующий `DAGI_HOME`, его права не меняются. API-ключ читается только из переменной окружения и не сохраняется в репозитории или базе.

## Запуск

Нужны Python 3.11–3.14 и `uv`.

```bash
uv sync
export DAGI_API_KEY="..."
export DAGI_MODEL="gpt-4o-mini"
# Для OpenRouter или другого OpenAI-compatible endpoint:
# export DAGI_BASE_URL="https://openrouter.ai/api/v1"
# export DAGI_MODEL="provider/model"
uv run dagi
```

Переменные окружения:

- `DAGI_API_KEY` — обязательный ключ.
- `DAGI_BASE_URL` — API endpoint, по умолчанию `https://api.openai.com/v1`.
- `DAGI_MODEL` — модель, по умолчанию `gpt-4o-mini`.
- `DAGI_HOME` — база и навыки, по умолчанию `~/.dagi`.
- `DAGI_WORKSPACE` — корень файловых инструментов, по умолчанию текущий каталог.
- `DAGI_ENABLE_SHELL=1` — включает shell с подтверждением каждой команды.

Команды: `/help`, `/new`, `/memory <запрос>`, `/skills`, `/model`, `/exit`. Навыки модель может сохранять инструментом `create_skill` и загружать через `use_skill`.

## Проверки

```bash
uv sync --extra dev
uv run python -m pytest -q
uv build
```

Тесты не требуют API-ключа и не обращаются к модели.

## Структура

```text
dagi_core/agent.py     цикл агента, бюджет итераций и запись tool-call до выполнения
dagi_core/provider.py  один OpenAI-compatible потоковый адаптер
dagi_core/tools.py     рабочие файлы, память, навыки и опциональный shell
dagi_core/state.py     SQLite, FTS5, сессии и навыки
dagi_core/config.py    переменные окружения
dagi_core/cli.py       единственная поверхность: терминал
```

## Происхождение

Первая версия `main` (`b14b0ba`) была прототипом на основе `Mohamedhasbini/hermes`; её код и MIT-уведомление остаются в истории Git. В текущей версии исходные модули заменены компактной реализацией, ориентированной на актуальный upstream Hermes, указанный выше. Подробности — в `NOTICE.md`.
