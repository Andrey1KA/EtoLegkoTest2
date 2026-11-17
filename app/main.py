from html import escape

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import settings
from app.creator import create_campaign
from app.database import SessionLocal
from app.models import Campaign
from app.editor import (
    add_offer,
    bring_back_offer,
    campaign_view,
    cancel_stream,
    fetch_streams,
    push_stream,
    remove_offer,
    page_chrome,
    streams_page,
    toggle_pin,
)
from app.keitaro import KeitaroClient, KeitaroError

app = FastAPI()


class CampaignForm(BaseModel):
    name: str
    geo: str
    offer_id: str = ""


class OfferForm(BaseModel):
    offer_id: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with SessionLocal() as session:
        campaigns = [
            {
                "name": campaign.name,
                "geo": campaign.geo,
                "keitaro_id": campaign.keitaro_id,
            }
            for campaign in session.query(Campaign).order_by(Campaign.id.desc())
            if campaign.keitaro_id
        ]
    return _page(campaigns)


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
    view = campaign_view(keitaro_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    return streams_page(view)


@app.post("/campaigns/{keitaro_id}/fetch")
def fetch_campaign(keitaro_id: int) -> dict[str, bool]:
    if campaign_view(keitaro_id) is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    try:
        fetch_streams(keitaro_id)
    except KeitaroError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"ok": True}


@app.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers")
def add_stream_offer(keitaro_id: int, stream_id: int, form: OfferForm) -> dict[str, bool]:
    if not form.offer_id.strip().isdigit():
        raise HTTPException(status_code=400, detail="Выберите оффер из списка")
    return _call(lambda: add_offer(keitaro_id, stream_id, int(form.offer_id)))


@app.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers/{binding_id}/remove")
def remove_stream_offer(keitaro_id: int, stream_id: int, binding_id: int) -> dict[str, bool]:
    return _call(lambda: remove_offer(keitaro_id, stream_id, binding_id))


@app.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers/{binding_id}/pin")
def pin_stream_offer(keitaro_id: int, stream_id: int, binding_id: int) -> dict[str, bool]:
    return _call(lambda: toggle_pin(keitaro_id, stream_id, binding_id))


@app.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers/{binding_id}/bring-back")
def bring_stream_offer(keitaro_id: int, stream_id: int, binding_id: int) -> dict[str, bool]:
    return _call(lambda: bring_back_offer(keitaro_id, stream_id, binding_id))


@app.post("/campaigns/{keitaro_id}/streams/{stream_id}/push")
def push_campaign_stream(keitaro_id: int, stream_id: int) -> dict[str, bool]:
    return _call(lambda: push_stream(keitaro_id, stream_id))


@app.post("/campaigns/{keitaro_id}/streams/{stream_id}/cancel")
def cancel_campaign_stream(keitaro_id: int, stream_id: int) -> dict[str, bool]:
    return _call(lambda: cancel_stream(keitaro_id, stream_id))


def _call(action) -> dict[str, bool]:
    try:
        action()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except KeitaroError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"ok": True}


def _page(campaigns: list[dict]) -> str:
    if campaigns:
        items = "".join(
            "<li>"
            f'<a href="/campaigns/{item["keitaro_id"]}">'
            f'<strong>{escape(item["name"])}</strong>'
            f'<span>{escape(item["geo"])} · #{item["keitaro_id"]}</span>'
            "</a></li>"
            for item in campaigns
        )
        campaign_list = f"<ul class='campaigns'>{items}</ul>"
    else:
        campaign_list = "<p class='empty'>Пока нет ни одной кампании.</p>"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Создание кампании</title>
  <style>
    {page_chrome()}
    .layout {{ display: grid; grid-template-columns: minmax(0, 28rem) minmax(16rem, 22rem); gap: 1.25rem; align-items: start; }}
    form label {{ display: block; margin-top: 0.9rem; font-size: 0.78rem; font-weight: 650; letter-spacing: 0.04em; text-transform: uppercase; color: #667; }}
    input {{ width: 100%; box-sizing: border-box; margin-top: 0.35rem; height: 2.5rem; padding: 0 0.7rem; border: 1px solid #d5dbe3; border-radius: 8px; font: inherit; background: #fff; }}
    input:focus {{ outline: 2px solid #c9ead8; border-color: #1b6b3a; }}
    .field {{ position: relative; }}
    #offers {{ position: absolute; z-index: 3; left: 0; right: 0; margin: 0.25rem 0 0; padding: 0.25rem; list-style: none; background: #fff; border: 1px solid #e3e6ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(20, 32, 26, 0.12); max-height: 16rem; overflow: auto; }}
    #offers:empty {{ display: none; }}
    #offers li {{ padding: 0.55rem 0.65rem; border-radius: 6px; cursor: pointer; }}
    #offers li:hover {{ background: #f3f7f4; }}
    button[type=submit] {{ margin-top: 1.2rem; width: 100%; height: 2.6rem; border: 0; border-radius: 8px; background: #1b6b3a; color: #fff; font-weight: 650; cursor: pointer; }}
    button[type=submit]:hover {{ background: #155a30; }}
    .side h2 {{ margin: 0 0 0.8rem; font-size: 1rem; }}
    .campaigns {{ list-style: none; margin: 0; padding: 0; }}
    .campaigns a {{ display: flex; flex-direction: column; gap: 0.15rem; padding: 0.7rem 0; border-bottom: 1px solid #eef1f4; color: inherit; text-decoration: none; }}
    .campaigns a:hover strong {{ color: #1b6b3a; }}
    .campaigns span, .empty {{ color: #778; font-size: 0.85rem; }}
    #result:empty {{ display: none; }}
    #result {{ margin-bottom: 0.8rem; padding: 0.7rem 0.8rem; border-radius: 8px; background: #eef8f1; }}
    #result .error {{ color: #a40000; background: transparent; }}
    #result:has(.error) {{ background: #fff1f1; }}
    @media (max-width: 800px) {{ .layout {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header class="top">
    <strong>Keitaro wrapper</strong>
    <span>Development</span>
  </header>
  <nav class="nav">
    <a class="on" href="/">Создание</a>
  </nav>
  <main>
    <p class="crumb">Campaigns / Новая кампания</p>
    <div class="layout">
      <section class="card">
        <h1>Создание кампании</h1>
        <div id="result"></div>
        <form>
          <label>Name <input name="name" placeholder="test_kalinnik_campaign3" required></label>
          <label>Geo <input name="geo" placeholder="AU или MX,AU" required></label>
          <label class="field">Offer
            <input id="offer-query" placeholder="id или часть названия" autocomplete="off">
            <ul id="offers"></ul>
          </label>
          <input type="hidden" id="offer-id">
          <p><button type="submit">Create</button></p>
        </form>
      </section>
      <aside class="card side">
        <h2>Уже созданные</h2>
        {campaign_list}
      </aside>
    </div>
  </main>
  <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
  <script>
    let timer = null;

    $("form").on("submit", function (event) {{
      event.preventDefault();
      $.ajax({{
        url: "/campaigns",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({{
          name: $("input[name=name]").val(),
          geo: $("input[name=geo]").val(),
          offer_id: $("#offer-id").val()
        }}),
        success: function (result) {{
          const box = $("#result").empty();
          $("<p>").text(result.message).toggleClass("error", !result.ok).appendTo(box);
          if (!result.ok) {{
            return;
          }}
          $("<p>").append(
            $("<a>").attr("href", result.admin_url).text("Кампания в Keitaro")
          ).appendTo(box);
          $("<p>").append(
            $("<a>").attr("href", result.streams_url).text("Потоки кампании")
          ).appendTo(box);
        }}
      }});
    }});

    $("#offer-query").on("input", function () {{
      $("#offer-id").val("");
      clearTimeout(timer);
      const query = $(this).val().trim();
      timer = setTimeout(function () {{
        if (query.length < 2) {{
          $("#offers").empty();
          return;
        }}
        $.getJSON("/api/offers", {{ q: query }}, function (items) {{
          const list = $("#offers").empty();
          items.forEach(function (item) {{
            $("<li>").text(item.id + " " + item.name).on("click", function () {{
              $("#offer-id").val(item.id);
              $("#offer-query").val(item.name);
              list.empty();
            }}).appendTo(list);
          }});
        }});
      }}, 300);
    }});
  </script>
</body>
</html>
"""
