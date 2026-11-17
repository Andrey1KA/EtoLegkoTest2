import sys

from app.creator import create_campaign
from app.keitaro import KeitaroError


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "Использование: python -m app.create_campaign <имя> <гео> <id оффера>"
        )

    name, geo, offer_argument = sys.argv[1:]
    try:
        offer_id = int(offer_argument)
        keitaro_id, saved_name = create_campaign(name, geo, offer_id)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    print(f"Кампания {keitaro_id}: {saved_name}")
    print(f"https://tlgk.host/admin/#!/campaign/{keitaro_id}/main")


if __name__ == "__main__":
    try:
        main()
    except KeitaroError as error:
        raise SystemExit(str(error)) from error
