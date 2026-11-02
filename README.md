# katteni_server

Новый сервер фермы. Старый Django сюда не копируется.

## Что нужно

- Python 3.10 или новее
- Postgres службой Windows (окно UAC подтверждает человек)
- Файл `farm.local.json` рядом с `manage.py` — секреты, в git не входит

## Первый запуск на этой машине

1. Создайте базу и пользователя Postgres (имена как в `farm.local.example.json`, пароль свой).
2. Скопируйте `farm.local.example.json` в `farm.local.json` и заполните: `secret_key`, пользователь и пароль базы. Токены Telegram и солвера — когда появятся вызовы наружу, не в git.
3. В каталоге репозитория:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-farm.txt
python manage.py migrate
```

4. Двойной щелчок `start-test.bat` — сайт на `http://127.0.0.1:8000/` и часы расписания в фоне. Проверка: `http://127.0.0.1:8000/health/` отвечает JSON `ok`. Лог часов: `logs\farm_clock.log`. Агент — отдельно `start-agent-hidden.bat`. Пароля в bat нет.

## Тесты

```bat
python manage.py test farm_core.tests farm_core.tests_circle farm_core.tests_persist farm_core.tests_modes farm_api.tests farm_console.tests farm_agent_api.tests farm_agent.tests_agent farm_agent.tests_search farm_agent.tests_close
```

Явные метки модулей: каталоги приложений без `__init__.py`.

## Ферма

Код туда — `git pull` и свой `farm.local.json`. Базу с этой машины не копируют.
