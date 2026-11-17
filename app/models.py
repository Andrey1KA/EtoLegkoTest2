from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str]

    bindings: Mapped[list["StreamOffer"]] = relationship(back_populates="offer")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    keitaro_id: Mapped[int | None] = mapped_column(unique=True)
    geo: Mapped[str] = mapped_column(default="")

    streams: Mapped[list["Stream"]] = relationship(back_populates="campaign")


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    keitaro_id: Mapped[int | None] = mapped_column(unique=True)
    name: Mapped[str]
    position: Mapped[int]
    kind: Mapped[str]
    synced_snapshot: Mapped[str | None]

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(back_populates="stream")


class StreamOffer(Base):
    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"))
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    position: Mapped[int]
    share: Mapped[int] = mapped_column(default=0)
    pinned: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default="active")

    stream: Mapped[Stream] = relationship(back_populates="offers")
    offer: Mapped[Offer] = relationship(back_populates="bindings")
