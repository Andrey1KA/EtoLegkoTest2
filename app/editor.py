import json

from app.config import settings
from app.database import SessionLocal
from app.keitaro import KeitaroClient
from app.models import Campaign, Offer, Stream, StreamOffer
from app.weights import apply_shares


def campaign_view(keitaro_id: int) -> dict | None:
    with SessionLocal() as session:
        campaign = session.query(Campaign).filter_by(keitaro_id=keitaro_id).one_or_none()
        if campaign is None:
            return None
        streams = []
        for stream in sorted(campaign.streams, key=lambda item: item.position):
            offers = [
                {
                    "id": binding.id,
                    "name": binding.offer.name,
                    "share": binding.share,
                    "status": binding.status,
                    "pinned": bool(binding.pinned),
                }
                for binding in sorted(stream.offers, key=lambda item: item.position)
            ]
            streams.append(
                {
                    "id": stream.id,
                    "name": stream.name,
                    "position": stream.position,
                    "keitaro_id": stream.keitaro_id,
                    "kind": stream.kind,
                    "dirty": _is_dirty(stream),
                    "offers": offers,
                }
            )
        return {
            "name": campaign.name,
            "keitaro_id": campaign.keitaro_id,
            "admin_url": f"{settings.keitaro_base_url}/admin/#!/campaign/{campaign.keitaro_id}/main",
            "streams": streams,
        }


def fetch_streams(keitaro_id: int) -> None:
    client = KeitaroClient()
    remote_streams = client.streams(keitaro_id)
    with SessionLocal() as session:
        campaign = session.query(Campaign).filter_by(keitaro_id=keitaro_id).one_or_none()
        if campaign is None:
            raise LookupError("Кампания не найдена")

        remote_ids = {item.id for item in remote_streams}
        for stream in list(campaign.streams):
            if stream.keitaro_id not in remote_ids:
                _clear_offers(session, stream)
                session.delete(stream)
        session.flush()

        for item in remote_streams:
            stream = _stream_by_keitaro_id(campaign, item.id)
            if stream is None:
                stream = Stream(
                    campaign_id=campaign.id,
                    keitaro_id=item.id,
                    name=item.name,
                    position=item.position,
                    kind="offers" if item.offers else "plain",
                    synced_snapshot="[]",
                )
                session.add(stream)
                session.flush()

            stream.name = item.name
            stream.position = item.position
            _sync_offers(session, client, stream, item.offers)
        session.commit()


def add_offer(keitaro_id: int, stream_id: int, offer_id: int) -> None:
    client = KeitaroClient()
    with SessionLocal() as session:
        stream = _own_stream(session, keitaro_id, stream_id)
        if stream.kind != "offers":
            raise ValueError("В этот поток офферы не добавляются")
        offer = _local_offer(session, client, offer_id)
        if any(binding.offer_id == offer.id for binding in stream.offers):
            raise ValueError("Оффер уже в потоке")
        position = max((binding.position for binding in stream.offers), default=0) + 1
        session.add(
            StreamOffer(
                stream_id=stream.id,
                offer_id=offer.id,
                position=position,
                share=0,
                pinned=False,
                status="active",
            )
        )
        session.flush()
        session.expire(stream, ["offers"])
        apply_shares(list(stream.offers))
        session.commit()


def remove_offer(keitaro_id: int, stream_id: int, binding_id: int) -> None:
    _set_status(keitaro_id, stream_id, binding_id, "removed", "Оффер уже снят")


def bring_back_offer(keitaro_id: int, stream_id: int, binding_id: int) -> None:
    _set_status(keitaro_id, stream_id, binding_id, "active", "Оффер уже в потоке")


def toggle_pin(keitaro_id: int, stream_id: int, binding_id: int) -> None:
    with SessionLocal() as session:
        stream = _own_stream(session, keitaro_id, stream_id)
        binding = session.get(StreamOffer, binding_id)
        if binding is None or binding.stream_id != stream.id:
            raise LookupError("Оффер в потоке не найден")
        if binding.status != "active":
            raise ValueError("Снятый оффер нельзя запинить")
        binding.pinned = not binding.pinned
        apply_shares(list(stream.offers))
        session.commit()


def push_stream(keitaro_id: int, stream_id: int) -> None:
    client = KeitaroClient()
    with SessionLocal() as session:
        stream = _own_stream(session, keitaro_id, stream_id)
        active = [
            binding
            for binding in sorted(stream.offers, key=lambda item: item.position)
            if binding.status == "active"
        ]
        client.replace_stream_offers(
            stream.keitaro_id,
            [
                {"offer_id": binding.offer.keitaro_id, "share": binding.share}
                for binding in active
            ],
        )
        stream.synced_snapshot = json.dumps(_rows(stream))
        session.commit()


def cancel_stream(keitaro_id: int, stream_id: int) -> None:
    with SessionLocal() as session:
        stream = _own_stream(session, keitaro_id, stream_id)
        saved = json.loads(stream.synced_snapshot or "[]")
        saved_ids = {item["keitaro_offer_id"] for item in saved}
        for binding in list(stream.offers):
            if binding.offer.keitaro_id not in saved_ids:
                session.delete(binding)
        session.flush()
        session.expire(stream, ["offers"])
        by_keitaro = {binding.offer.keitaro_id: binding for binding in stream.offers}
        for item in saved:
            binding = by_keitaro[item["keitaro_offer_id"]]
            binding.share = item["share"]
            binding.pinned = item["pinned"]
            binding.status = item["status"]
            binding.position = item["position"]
        session.commit()


def streams_page(view: dict) -> str:
    blocks = []
    for stream in view["streams"]:
        title = (
            f"Flow {stream['position']}. {_escape(stream['name'])} "
            f"#{stream['keitaro_id']}"
        )
        if stream["kind"] != "offers":
            blocks.append(f'<section class="stream"><h2>{title}</h2></section>')
            continue
        rows = "".join(_offer_row(offer) for offer in stream["offers"])
        draft = ""
        if stream["dirty"]:
            draft = (
                '<p class="draft">'
                '<button type="button" class="push">Push to KT</button>'
                '<button type="button" class="cancel">Cancel</button>'
                "</p>"
            )
        css = "stream dirty" if stream["dirty"] else "stream"
        blocks.append(
            f"""<section class="{css}" data-stream="{stream["id"]}">
  <h2>{title}</h2>
  {draft}
  <table>
    <thead><tr><th>Offer</th><th>Share</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p>
    <input class="offer-query" placeholder="Оффер" autocomplete="off">
    <input class="offer-id" type="hidden">
    <button type="button" class="add">Add</button>
  </p>
  <ul class="found"></ul>
</section>"""
        )
    body = "".join(blocks) or "<p>Потоков ещё нет.</p>"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{_escape(view["name"])}</title>
  <style>
    body {{ font-family: sans-serif; max-width: 50rem; margin: 2rem; background: #fff; }}
    .stream {{ border: 1px solid #ccc; margin-top: 1rem; padding: 1rem; background: #fff; }}
    .stream.dirty {{ background: #ffe58a; }}
    ul {{ list-style: none; padding: 0; margin: 0; }}
    li {{ padding: 0.3rem; cursor: pointer; }}
    li:hover {{ background: #f3f3f3; }}
    table {{ border-collapse: collapse; width: 100%; }}
    td, th {{ text-align: left; padding: 0.4rem; border-bottom: 1px solid #eee; }}
    tr.removed {{ color: #888; background: #eee; }}
    button, a.button {{ margin-right: 0.5rem; }}
    .pin.on {{ background: #333; color: #fff; }}
  </style>
</head>
<body>
  <p><a href="/">К форме</a></p>
  <h1>{_escape(view["name"])}</h1>
  <p>
    <button type="button" id="fetch">Fetch streams from KT</button>
    <a href="{_escape(view["admin_url"])}">View in KT</a>
  </p>
  <p id="result"></p>
  {body}
  <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
  <script>
    function showError(xhr, fallback) {{
      const detail = xhr.responseJSON && xhr.responseJSON.detail;
      $("#result").text(detail || fallback);
    }}

    $("#fetch").on("click", function () {{
      $("#result").text("Читаем потоки...");
      $.ajax({{ url: location.pathname + "/fetch", method: "POST" }})
        .done(function () {{ location.reload(); }})
        .fail(function (xhr) {{ showError(xhr, "Не удалось прочитать потоки"); }});
    }});

    let timer = null;
    $(".offer-query").on("input", function () {{
      const section = $(this).closest("section");
      section.find(".offer-id").val("");
      clearTimeout(timer);
      const query = $(this).val().trim();
      timer = setTimeout(function () {{
        const list = section.find(".found").empty();
        if (query.length < 2) {{
          return;
        }}
        $.getJSON("/api/offers", {{ q: query }}, function (items) {{
          list.empty();
          items.forEach(function (item) {{
            $("<li>").text(item.id + " " + item.name).on("click", function () {{
              section.find(".offer-id").val(item.id);
              section.find(".offer-query").val(item.name);
              list.empty();
            }}).appendTo(list);
          }});
        }});
      }}, 300);
    }});

    $(".add").on("click", function () {{
      const section = $(this).closest("section");
      $("#result").text("Добавляем оффер...");
      $.ajax({{
        url: location.pathname + "/streams/" + section.data("stream") + "/offers",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({{ offer_id: String(section.find(".offer-id").val()) }})
      }}).done(function () {{
        location.reload();
      }}).fail(function (xhr) {{
        showError(xhr, "Не удалось добавить оффер");
      }});
    }});

    $(".push").on("click", function () {{
      const section = $(this).closest("section");
      $("#result").text("Публикуем поток...");
      $.ajax({{
        url: location.pathname + "/streams/" + section.data("stream") + "/push",
        method: "POST"
      }}).done(function () {{
        location.reload();
      }}).fail(function (xhr) {{
        showError(xhr, "Не удалось опубликовать поток");
      }});
    }});

    $(".remove").on("click", function () {{
      const section = $(this).closest("section");
      const binding = $(this).data("binding");
      $("#result").text("Снимаем оффер...");
      $.ajax({{
        url: location.pathname + "/streams/" + section.data("stream") + "/offers/" + binding + "/remove",
        method: "POST"
      }}).done(function () {{
        location.reload();
      }}).fail(function (xhr) {{
        showError(xhr, "Не удалось снять оффер");
      }});
    }});

    $(".pin").on("click", function () {{
      const section = $(this).closest("section");
      const binding = $(this).data("binding");
      $("#result").text("Меняем пин...");
      $.ajax({{
        url: location.pathname + "/streams/" + section.data("stream") + "/offers/" + binding + "/pin",
        method: "POST"
      }}).done(function () {{
        location.reload();
      }}).fail(function (xhr) {{
        showError(xhr, "Не удалось запинить долю");
      }});
    }});

    $(".bring").on("click", function () {{
      const section = $(this).closest("section");
      const binding = $(this).data("binding");
      $("#result").text("Возвращаем оффер...");
      $.ajax({{
        url: location.pathname + "/streams/" + section.data("stream") + "/offers/" + binding + "/bring-back",
        method: "POST"
      }}).done(function () {{
        location.reload();
      }}).fail(function (xhr) {{
        showError(xhr, "Не удалось вернуть оффер");
      }});
    }});

    $(".cancel").on("click", function () {{
      const section = $(this).closest("section");
      $("#result").text("Отменяем черновик...");
      $.ajax({{
        url: location.pathname + "/streams/" + section.data("stream") + "/cancel",
        method: "POST"
      }}).done(function () {{
        location.reload();
      }}).fail(function (xhr) {{
        showError(xhr, "Не удалось отменить черновик");
      }});
    }});
  </script>
</body>
</html>
"""


def _offer_row(offer: dict) -> str:
    removed = offer["status"] == "removed"
    name = _escape(offer["name"])
    if removed:
        name = f"{name} (removed)"
        button = (
            f'<button type="button" class="bring" data-binding="{offer["id"]}">'
            "Bring back</button>"
        )
        css = ' class="removed"'
    else:
        button = (
            f'<button type="button" class="remove" data-binding="{offer["id"]}">'
            "Remove</button>"
        )
        css = ""
    pin = ""
    if not removed:
        mark = "on" if offer["pinned"] else ""
        label = "Unpin" if offer["pinned"] else "Pin"
        pin = (
            f'<button type="button" class="pin {mark}" data-binding="{offer["id"]}">'
            f"{label}</button> "
        )
    return (
        f"<tr{css}>"
        f"<td>{name}</td>"
        f"<td>{pin}{offer['share']}%</td>"
        f"<td>{button}</td>"
        "</tr>"
    )


def _set_status(
    keitaro_id: int,
    stream_id: int,
    binding_id: int,
    status: str,
    already: str,
) -> None:
    with SessionLocal() as session:
        stream = _own_stream(session, keitaro_id, stream_id)
        binding = session.get(StreamOffer, binding_id)
        if binding is None or binding.stream_id != stream.id:
            raise LookupError("Оффер в потоке не найден")
        if binding.status == status:
            raise ValueError(already)
        binding.status = status
        apply_shares(list(stream.offers))
        session.commit()


def _rows(stream: Stream) -> list[dict]:
    return [
        {
            "keitaro_offer_id": binding.offer.keitaro_id,
            "share": binding.share,
            "pinned": binding.pinned,
            "status": binding.status,
            "position": binding.position,
        }
        for binding in sorted(stream.offers, key=lambda item: item.position)
    ]


def _is_dirty(stream: Stream) -> bool:
    saved = json.loads(stream.synced_snapshot or "[]")
    return saved != _rows(stream)


def _own_stream(session, keitaro_id: int, stream_id: int) -> Stream:
    stream = session.get(Stream, stream_id)
    if stream is None or stream.campaign.keitaro_id != keitaro_id:
        raise LookupError("Поток не найден")
    return stream


def _stream_by_keitaro_id(campaign: Campaign, keitaro_id: int) -> Stream | None:
    for stream in campaign.streams:
        if stream.keitaro_id == keitaro_id:
            return stream
    return None


def _sync_offers(session, client: KeitaroClient, stream: Stream, remote_offers) -> None:
    saved = json.loads(stream.synced_snapshot or "[]")
    known_ids = {item["keitaro_offer_id"] for item in saved}
    previous = {binding.offer.keitaro_id: binding for binding in list(stream.offers)}
    remote_ids = {item.offer_id for item in remote_offers}

    for offer_id, binding in list(previous.items()):
        if offer_id not in remote_ids and offer_id not in known_ids:
            session.delete(binding)
            del previous[offer_id]
    session.flush()

    snapshot = []
    position = 1
    for remote_offer in remote_offers:
        local_offer = _local_offer(session, client, remote_offer.offer_id)
        binding = previous.get(remote_offer.offer_id)
        pinned = bool(binding.pinned) if binding is not None else False
        if binding is None:
            binding = StreamOffer(
                stream_id=stream.id,
                offer_id=local_offer.id,
                position=position,
                share=remote_offer.share,
                pinned=False,
                status="active",
            )
            session.add(binding)
        else:
            binding.position = position
            binding.share = remote_offer.share
            binding.pinned = pinned
            binding.status = "active"
        snapshot.append(
            {
                "keitaro_offer_id": remote_offer.offer_id,
                "share": remote_offer.share,
                "pinned": pinned,
                "status": "active",
                "position": position,
            }
        )
        position += 1

    missing = [
        (offer_id, binding)
        for offer_id, binding in previous.items()
        if offer_id not in remote_ids
    ]
    missing.sort(key=lambda pair: pair[1].position)
    for offer_id, binding in missing:
        binding.position = position
        binding.share = 0
        binding.pinned = False
        binding.status = "removed"
        snapshot.append(
            {
                "keitaro_offer_id": offer_id,
                "share": 0,
                "pinned": False,
                "status": "removed",
                "position": position,
            }
        )
        position += 1

    stream.kind = "offers" if remote_offers or missing else "plain"
    stream.synced_snapshot = json.dumps(snapshot)


def _clear_offers(session, stream: Stream) -> None:
    for binding in list(stream.offers):
        session.delete(binding)
    session.flush()


def _local_offer(session, client: KeitaroClient, offer_id: int) -> Offer:
    remote = client.offer(offer_id)
    offer = session.query(Offer).filter_by(keitaro_id=offer_id).one_or_none()
    if offer is None:
        offer = Offer(keitaro_id=remote.id, name=remote.name)
        session.add(offer)
        session.flush()
        return offer
    offer.name = remote.name
    return offer


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
