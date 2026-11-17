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
        for stream in sorted(
            campaign.streams,
            key=lambda item: (item.kind != "offers", item.position),
        ):
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


def page_chrome() -> str:
    return """
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #f3f5f7; color: #243028; }
    a { color: #1b6b3a; }
    .top { display: flex; justify-content: space-between; align-items: center; padding: 0.55rem 1.25rem; background: #1b6b3a; color: #fff; }
    .top span { font-size: 0.72rem; letter-spacing: 0.12em; text-transform: uppercase; opacity: 0.85; }
    .nav { display: flex; gap: 0.2rem; padding: 0 1rem; background: #14343c; }
    .nav a { color: #d5e4ea; text-decoration: none; padding: 0.72rem 0.9rem; }
    .nav a.on, .nav a:hover { color: #fff; background: rgba(255,255,255,0.08); }
    main { padding: 0 1.25rem 2.5rem; }
    .crumb { margin: 0; padding: 0.8rem 0; color: #6d7880; font-size: 0.9rem; }
    .crumb a { color: #1b6b3a; text-decoration: none; }
    .card { background: #fff; border: 1px solid #e3e6ea; border-radius: 12px; padding: 1.15rem 1.2rem 1.25rem; box-shadow: 0 1px 2px rgba(20,32,26,0.04); }
    h1 { margin: 0 0 0.2rem; font-size: 1.35rem; }
    """


def streams_page(view: dict) -> str:
    blocks = []
    for stream in view["streams"]:
        title = (
            f"Flow {stream['position']}. {_escape(stream['name'])} "
            f"#{stream['keitaro_id']}"
        )
        if stream["kind"] != "offers":
            blocks.append(
                f'<section class="card stream plain"><h2>{title}</h2>'
                "<p class='note'>Поток без офферов</p>"
                "</section>"
            )
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
        css = "card stream dirty" if stream["dirty"] else "card stream"
        blocks.append(
            f"""<section class="{css}" data-stream="{stream["id"]}">
  <div class="stream-head">
    <h2>{title}</h2>
    {draft}
  </div>
  <table>
    <thead>
      <tr>
        <th></th>
        <th>Share</th>
        <th>Stats</th>
        <th>Trends</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {rows}
      <tr class="add-row">
        <td colspan="5">
          <input class="offer-query" placeholder="Оффер" autocomplete="off">
          <input class="offer-id" type="hidden">
          <button type="button" class="add">Add</button>
          <ul class="found"></ul>
        </td>
      </tr>
    </tbody>
  </table>
</section>"""
        )
    body = "".join(blocks) or "<p>Потоков ещё нет.</p>"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{_escape(view["name"])}</title>
  <style>
    {page_chrome()}
    .toolbar {{ display: flex; gap: 0.5rem; margin-bottom: 1rem; }}
    .tool, .push, .cancel, .add, .remove, .bring, .pin {{
      display: inline-flex; align-items: center; gap: 0.35rem;
      border: 1px solid #d5dbe3; background: #fff; color: #243028;
      padding: 0.5rem 0.8rem; border-radius: 8px; font-size: 0.78rem;
      font-weight: 650; letter-spacing: 0.03em; text-decoration: none;
      cursor: pointer; white-space: nowrap;
    }}
    .tool {{ text-transform: uppercase; }}
    .tool:hover, .add:hover, .remove:hover, .bring:hover, .cancel:hover {{ background: #f6f8f7; }}
    .push {{ background: #1b6b3a; border-color: #1b6b3a; color: #fff; }}
    .push:hover {{ background: #155a30; }}
    #result:empty {{ display: none; }}
    #result {{ margin: 0 0 0.8rem; color: #a40000; }}
    .stream {{ margin-bottom: 1rem; overflow: visible; padding: 0; }}
    .stream-head, .stream.plain {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.85rem 1rem; }}
    .stream.plain {{ display: block; }}
    .stream h2 {{ margin: 0; font-size: 1rem; }}
    .stream.dirty {{ background: #ffedad; border-color: #eed44d; }}
    .stream.dirty .stream-head,
    .stream.dirty th,
    .stream.dirty td,
    .stream.dirty .add-row td {{ background: transparent; }}
    .stream.dirty tr.removed {{ background: rgba(0, 0, 0, 0.06); }}
    .draft {{ display: flex; align-items: center; gap: 0.45rem; margin: 0; }}
    .note {{ margin: 0 1rem 0.9rem; color: #6d7880; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th {{ color: #7b868e; font-weight: 600; font-size: 0.78rem; letter-spacing: 0.04em; text-transform: uppercase; text-align: center; padding: 0.75rem; border-bottom: 1px solid #e8edf0; background: #fafbfc; }}
    th:first-child {{ text-align: left; }}
    th:nth-child(2) {{ width: 9.5rem; }}
    th:nth-child(3), th:nth-child(4) {{ width: 6rem; }}
    th:nth-child(5) {{ width: 8.5rem; }}
    td {{ padding: 0.8rem 0.75rem; border-bottom: 1px solid #eef1f4; vertical-align: middle; overflow-wrap: anywhere; }}
    td:nth-child(n+2) {{ text-align: center; }}
    tr:last-child td {{ border-bottom: 0; }}
    tr.removed {{ color: #8b949c; background: #f7f8f9; }}
    .share-line {{ display: flex; align-items: center; justify-content: center; gap: 0.4rem; }}
    .bar {{ height: 4px; margin-top: 0.4rem; border-radius: 99px; background: #e7ece8; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: #1b6b3a; }}
    .muted {{ color: #c5ced4; }}
    .offer-query {{ width: min(24rem, 70%); height: 2.3rem; padding: 0 0.7rem; border: 1px solid #d5dbe3; border-radius: 8px; font: inherit; }}
    .add-row td {{ position: relative; background: #fcfdfc; }}
    ul.found {{ position: absolute; z-index: 5; left: 0.75rem; width: min(36rem, calc(100% - 1.5rem)); top: 100%; margin: 0.35rem 0 0; padding: 0.25rem; list-style: none; background: #fff; border: 1px solid #e3e6ea; border-radius: 8px; box-shadow: 0 10px 28px rgba(20,32,26,0.12); max-height: 16rem; overflow: auto; }}
    ul.found:empty {{ display: none; }}
    li {{ padding: 0.5rem 0.65rem; border-radius: 6px; cursor: pointer; text-align: left; }}
    li:hover {{ background: #f3f7f4; }}
    .pin {{ width: 2rem; height: 2rem; padding: 0; justify-content: center; border-radius: 999px; color: #1b6b3a; }}
    .pin svg {{ display: block; }}
    .pin.on {{ background: #1b6b3a; border-color: #1b6b3a; color: #fff; }}
  </style>
</head>
<body>
  <header class="top">
    <strong>Keitaro wrapper</strong>
    <span>Development</span>
  </header>
  <nav class="nav">
    <a href="/">Создание</a>
    <a class="on" href="/campaigns/{view["keitaro_id"]}">Потоки</a>
  </nav>
  <main>
  <p class="crumb"><a href="/">Campaigns</a> / {_escape(view["name"])} / Keitaro Streams</p>
  <div class="toolbar">
    <button type="button" id="fetch" class="tool">↓ Fetch streams from KT</button>
    <a class="tool" href="{_escape(view["admin_url"])}">View in KT ↗</a>
  </div>
  <p id="result"></p>
  {body}
  </main>
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

    function postOffer(section) {{
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
    }}

    function showOffers(section) {{
      const query = section.find(".offer-query").val().trim();
      const list = section.find(".found").empty();
      if (query.length < 2) {{
        return;
      }}
      $("#result").text("Ищем оффер...");
      $.getJSON("/api/offers", {{ q: query }}, function (items) {{
        list.empty();
        if (!items.length) {{
          $("#result").text("Ничего не найдено");
          return;
        }}
        $("#result").empty();
        items.forEach(function (item) {{
          $("<li>").text(item.id + " " + item.name).on("click", function () {{
            section.find(".offer-id").val(item.id);
            section.find(".offer-query").val(item.name);
            list.empty();
          }}).appendTo(list);
        }});
      }}).fail(function () {{
        $("#result").text("Не удалось найти оффер");
      }});
    }}

    let timer = null;
    $(".offer-query").on("input", function () {{
      const section = $(this).closest("section");
      section.find(".offer-id").val("");
      section.find(".found").empty();
      clearTimeout(timer);
      timer = setTimeout(function () {{
        showOffers(section);
      }}, 500);
    }});

    $(".add").on("click", function () {{
      const section = $(this).closest("section");
      if (!section.find(".offer-id").val()) {{
        $("#result").text("Выберите оффер из списка");
        return;
      }}
      postOffer(section);
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
            f'<button type="button" class="pin {mark}" data-binding="{offer["id"]}" '
            f'aria-label="{label}" title="{label}">'
            '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">'
            '<path fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linejoin="round" d="M8 3h8v5l2 3v2H6v-2l2-3V3z"/>'
            '<path fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" d="M12 13v8M9 3h6"/>'
            "</svg></button> "
        )
    return (
        f"<tr{css}>"
        f"<td>{name}</td>"
        f"<td><div class='share-line'>{pin}<b>{offer['share']}%</b></div>"
        f"<div class='bar'><span style='width:{offer['share']}%'></span></div></td>"
        "<td class='muted'>—</td>"
        "<td class='muted'>—</td>"
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
    offer = session.query(Offer).filter_by(keitaro_id=offer_id).one_or_none()
    if offer is not None:
        return offer
    remote = client.offer(offer_id)
    offer = Offer(keitaro_id=remote.id, name=remote.name)
    session.add(offer)
    session.flush()
    return offer


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
