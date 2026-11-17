from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.keitaro import KeitaroClient
from app.models import Campaign, Offer


def save_created_campaign(
    session: Session,
    name: str,
    countries: list[str],
    offer_id: int,
    offer_name: str,
    keitaro_campaign_id: int,
) -> tuple[int, str]:
    offer = session.query(Offer).filter_by(keitaro_id=offer_id).one_or_none()
    if offer is None:
        offer = Offer(keitaro_id=offer_id, name=offer_name)
        session.add(offer)
        session.flush()

    campaign = Campaign(
        name=name,
        keitaro_id=keitaro_campaign_id,
        geo=",".join(countries),
    )
    session.add(campaign)
    session.flush()

    keitaro_id = campaign.keitaro_id
    saved_name = campaign.name
    session.commit()
    return keitaro_id, saved_name


def create_campaign(name: str, geo: str, offer_id: int) -> tuple[int, str]:
    cleaned_name = name.strip()
    if not cleaned_name.startswith("test_"):
        raise ValueError("Имя кампании должно начинаться с test_")

    countries = [part.strip().upper() for part in geo.split(",") if part.strip()]
    if not countries:
        raise ValueError("Укажите гео-код, например AU или MX,AU")

    client = KeitaroClient()
    matches = [
        offer for offer in client.search_offers(str(offer_id)) if offer.id == offer_id
    ]
    if not matches:
        raise ValueError(f"Оффер {offer_id} не найден в Keitaro")

    campaign_id = client.create_campaign(cleaned_name, countries, offer_id)
    with SessionLocal() as session:
        return save_created_campaign(
            session,
            cleaned_name,
            countries,
            offer_id,
            matches[0].name,
            campaign_id,
        )
