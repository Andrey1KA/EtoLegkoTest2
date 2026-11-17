from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Обёртка Keitaro</title>
</head>
<body>
  <p>Каркас обёртки запущен.</p>
</body>
</html>
"""
