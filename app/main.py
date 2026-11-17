from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import settings
from app.creator import create_campaign
from app.database import SessionLocal
from app.keitaro import KeitaroClient, KeitaroError
from app.models import Campaign

app = FastAPI()


class CampaignForm(BaseModel):
    name: str
    geo: str
    offer_id: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _page()


@app.get("/api/offers")
def offers(q: str = Query(default="")) -> list[dict[str, int | str]]:
    query = q.strip()
    if len(query) < 2:
        return []
    found = KeitaroClient().search_offers(query)[:10]
    return [{"id": offer.id, "name": offer.name} for offer in found]


@app.post("/campaigns")
def create(form: CampaignForm) -> dict[str, str | bool]:
    if not form.offer_id.strip().isdigit():
        return {"ok": False, "message": "Выберите оффер из списка"}

    try:
        keitaro_id, saved_name = create_campaign(form.name, form.geo, int(form.offer_id))
    except ValueError as error:
        return {"ok": False, "message": str(error)}
    except KeitaroError as error:
        return {"ok": False, "message": str(error)}

    return {
        "ok": True,
        "message": f"Кампания {saved_name} создана.",
        "admin_url": f"{settings.keitaro_base_url}/admin/#!/campaign/{keitaro_id}/main",
        "streams_url": f"/campaigns/{keitaro_id}",
    }


@app.get("/campaigns/{keitaro_id}", response_class=HTMLResponse)
def campaign_page(keitaro_id: int) -> str:
    with SessionLocal() as session:
        campaign = session.query(Campaign).filter_by(keitaro_id=keitaro_id).one_or_none()
        if campaign is None:
            raise HTTPException(status_code=404, detail="Кампания не найдена")
        title = campaign.name
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{_escape(title)}</title>
</head>
<body>
  <p>Кампания {_escape(title)}. Потоки появятся на следующем шаге.</p>
  <p><a href="/">К форме</a></p>
</body>
</html>
"""


def _page() -> str:
    return """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Создание кампании</title>
  <style>
    body { font-family: sans-serif; max-width: 40rem; margin: 2rem; }
    label { display: block; margin-top: 1rem; }
    input { width: 100%; box-sizing: border-box; }
    ul { list-style: none; padding: 0; border: 1px solid #ccc; }
    li { padding: 0.4rem; cursor: pointer; }
    li:hover { background: #f3f3f3; }
    .error { color: #a40000; }
  </style>
</head>
<body>
  <h1>Создание кампании</h1>
  <div id="result"></div>
  <form>
    <label>Name <input name="name" required></label>
    <label>Geo <input name="geo" placeholder="AU или MX,AU" required></label>
    <label>Offer <input id="offer-query" autocomplete="off"></label>
    <input type="hidden" id="offer-id">
    <ul id="offers"></ul>
    <p><button type="submit">Create</button></p>
  </form>
  <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
  <script>
    let timer = null;

    $("form").on("submit", function (event) {
      event.preventDefault();
      $.ajax({
        url: "/campaigns",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({
          name: $("input[name=name]").val(),
          geo: $("input[name=geo]").val(),
          offer_id: $("#offer-id").val()
        }),
        success: function (result) {
          const box = $("#result").empty();
          $("<p>").text(result.message).toggleClass("error", !result.ok).appendTo(box);
          if (!result.ok) {
            return;
          }
          $("<p>").append(
            $("<a>").attr("href", result.admin_url).text("Кампания в Keitaro")
          ).appendTo(box);
          $("<p>").append(
            $("<a>").attr("href", result.streams_url).text("Потоки кампании")
          ).appendTo(box);
        }
      });
    });

    $("#offer-query").on("input", function () {
      $("#offer-id").val("");
      clearTimeout(timer);
      const query = $(this).val().trim();
      timer = setTimeout(function () {
        if (query.length < 2) {
          $("#offers").empty();
          return;
        }
        $.getJSON("/api/offers", { q: query }, function (items) {
          const list = $("#offers").empty();
          items.forEach(function (item) {
            $("<li>").text(item.id + " " + item.name).on("click", function () {
              $("#offer-id").val(item.id);
              $("#offer-query").val(item.name);
              list.empty();
            }).appendTo(list);
          });
        });
      }, 300);
    });
  </script>
</body>
</html>
"""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
