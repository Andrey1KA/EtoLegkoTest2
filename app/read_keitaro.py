import sys

from app.config import settings
from app.keitaro import KeitaroClient, KeitaroError


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Укажите id кампании: python -m app.read_keitaro <id> [поиск]")

    campaign_id = int(sys.argv[1])
    query = sys.argv[2] if len(sys.argv) > 2 else ""
    client = KeitaroClient()

    print(f"Кампания {campaign_id}: {client.campaign_name(campaign_id)}")
    _print_directory("Домен", client.find_domain(settings.keitaro_domain_name))
    _print_directory("Группа", client.find_group(settings.keitaro_group_name))
    _print_directory("Источник", client.find_source(settings.keitaro_source_name))

    print("Потоки:")
    for stream in client.streams(campaign_id):
        if not stream.offers:
            print(f"  {stream.position}. {stream.name}: без офферов")
            continue
        print(f"  {stream.position}. {stream.name}:")
        for offer in stream.offers:
            print(f"    оффер {offer.offer_id}, доля {offer.share}")

    if query:
        print(f"Офферы по запросу {query!r}:")
        for offer in client.search_offers(query)[:10]:
            print(f"  {offer.id} {offer.name}")


def _print_directory(title: str, item) -> None:
    if item is None:
        print(f"{title}: не найден")
        return
    print(f"{title}: {item.name} ({item.id})")


if __name__ == "__main__":
    try:
        main()
    except KeitaroError as error:
        raise SystemExit(str(error)) from error
