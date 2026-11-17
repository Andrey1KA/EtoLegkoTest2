# Обёртка над Keitaro

Нужен Python 3.11 или новее.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

На Windows виртуальное окружение включается так: `.venv\Scripts\activate`. Файл `.env` копируется командой `copy .env.example .env`.

После запуска откройте http://127.0.0.1:8000 . Ключ Keitaro в репозиторий не кладётся: его нужно вписать в свой `.env`.
