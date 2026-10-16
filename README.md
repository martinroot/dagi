# Dagi Core — минимальное ядро Hermes

Новый небольшой CLI-агент, собранный вокруг полезного ядра Hermes, а не ещё одной копии всей платформы.

## Что оставляем в ядре

- Цикл агента: запрос модели → поток текста и вызовы инструментов → результаты инструментов → продолжение ответа.
- Один адаптер OpenAI-compatible API: OpenAI, OpenRouter и совместимые endpoint настраиваются через URL и модель.
- SQLite + FTS5 для истории сессий и поиска по прошлым сообщениям.
- Навыки в читаемых Markdown-файлах и цикл извлечения повторяемой процедуры из сложной сессии.
- Минимальный CLI и базовые файловые инструменты, ограниченные рабочим каталогом.

## Чего здесь нет

Веб-панели, HTTP-сервера, мессенджер-шлюзов, MCP, cron, voice, multi-agent, профилей и удалённых sandbox/backend-интеграций. Это намеренно отдельное ядро, а не уменьшенная установка всех поверхностей Hermes.

## Безопасность инструментов

`DAGI_ENABLE_SHELL` по умолчанию выключен. Если включить его значением `1`, перед *каждой* командой `run_bash` CLI попросит подтверждение. Рабочий каталог ограничивает файловые инструменты, но не является OS-level sandbox для shell. История SQLite создаётся с правами `0600` на POSIX; API-ключ читается только из переменной окружения и не сохраняется в базе или репозитории.

## Быстрый запуск

Нужны Python 3.11+ и `uv`.

```bash
uv sync
export DAGI_API_KEY="..."
export DAGI_MODEL="gpt-4o-mini"
# Для OpenRouter или другого OpenAI-compatible endpoint:
# export DAGI_BASE_URL="https://openrouter.ai/api/v1"
# export DAGI_MODEL="provider/model"
uv run dagi
```

Настройки:

- `DAGI_API_KEY` — обязательный ключ провайдера.
- `DAGI_BASE_URL` — endpoint, по умолчанию `https://api.openai.com/v1`.
- `DAGI_MODEL` — модель, по умолчанию `gpt-4o-mini`.
- `DAGI_HOME` — хранилище, по умолчанию `~/.dagi`.
- `DAGI_WORKSPACE` — корень файловых инструментов, по умолчанию текущий каталог.
- `DAGI_ENABLE_SHELL=1` — включает shell-инструмент с подтверждением каждой команды.

Команды CLI: `/help`, `/skills`, `/memory <запрос>`, `/new`, `/learn`, `/model`, `/exit`.

## Проверки

```bash
uv sync --extra dev
uv run python -m pytest -q
```

Тесты не требуют API-ключа и не вызывают модель: цикл агента проверяется через тестовый провайдер.

## Структура

```text
hermes/agent/       цикл агента, prompt и инструменты
hermes/providers/   общий контракт и один OpenAI-compatible адаптер
hermes/memory/      история и полнотекстовый поиск SQLite/FTS5
hermes/skills/      Markdown-навыки
hermes/learning/    суммаризация и извлечение навыков
hermes/cli.py       единственная пользовательская поверхность — терминал
```

Часть начальной реализации адаптирована из [Mohamedhasbini/hermes](https://github.com/Mohamedhasbini/hermes), распространяемого по MIT License; исходное уведомление сохранено в `LICENSE`.
