import sys

from app.creator import save_created_campaign
from app.database import SessionLocal
from app.keitaro import KeitaroClient, KeitaroError


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "Использование: python -m app.create_campaign <имя> <гео> <id оффера>"
        )

    name, geo, offer_argument = sys.argv[1:]
    if not name.startswith("test_"):
        raise SystemExit("Имя кампании должно начинаться с test_")

    countries = [part.strip().upper() for part in geo.split(",") if part.strip()]
    if not countries:
        raise SystemExit("Укажите гео-код, например AU или MX,AU")

    offer_id = int(offer_argument)
    client = KeitaroClient()
    matches = [offer for offer in client.search_offers(str(offer_id)) if offer.id == offer_id]
    if not matches:
        raise SystemExit(f"Оффер {offer_id} не найден в Keitaro")

    campaign_id, streams = client.create_campaign(name, countries, offer_id)
    with SessionLocal() as session:
        keitaro_id, saved_name = save_created_campaign(
            session,
            name,
            countries,
            offer_id,
            matches[0].name,
            campaign_id,
            streams,
        )

    print(f"Кампания {keitaro_id}: {saved_name}")
    print(f"https://tlgk.host/admin/#!/campaign/{keitaro_id}/main")
    for stream in streams:
        if not stream.offers:
            print(f"  {stream.position}. {stream.name}: без офферов")
            continue
        shares = ", ".join(f"{item.offer_id} на {item.share}" for item in stream.offers)
        print(f"  {stream.position}. {stream.name}: {shares}")


if __name__ == "__main__":
    try:
        main()
    except KeitaroError as error:
        raise SystemExit(str(error)) from error
