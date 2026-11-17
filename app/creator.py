import json

from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient
from app.models import Campaign, Offer, Stream, StreamOffer


def save_created_campaign(
    session: Session,
    name: str,
    countries: list[str],
    offer_id: int,
    offer_name: str,
    keitaro_campaign_id: int,
    streams: list,
) -> Campaign:
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

    for item in streams:
        kind = "offers" if item.offers else "plain"
        snapshot = [
            {
                "keitaro_offer_id": stream_offer.offer_id,
                "share": stream_offer.share,
                "pinned": False,
                "status": "active",
                "position": index,
            }
            for index, stream_offer in enumerate(item.offers, start=1)
        ]
        stream = Stream(
            campaign_id=campaign.id,
            keitaro_id=item.id,
            name=item.name,
            position=item.position,
            kind=kind,
            synced_snapshot=json.dumps(snapshot),
        )
        session.add(stream)
        session.flush()
        if kind != "offers":
            continue
        for index, stream_offer in enumerate(item.offers, start=1):
            session.add(
                StreamOffer(
                    stream_id=stream.id,
                    offer_id=offer.id,
                    position=index,
                    share=stream_offer.share,
                    pinned=False,
                    status="active",
                )
            )

    keitaro_id = campaign.keitaro_id
    saved_name = campaign.name
    session.commit()
    return keitaro_id, saved_name
