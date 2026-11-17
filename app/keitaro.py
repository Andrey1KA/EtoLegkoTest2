import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import Settings, settings


class KeitaroError(Exception):
    pass


@dataclass(frozen=True)
class KeitaroOffer:
    id: int
    name: str


@dataclass(frozen=True)
class DirectoryItem:
    id: int
    name: str


@dataclass(frozen=True)
class StreamOffer:
    offer_id: int
    share: int


@dataclass(frozen=True)
class CampaignStream:
    id: int
    name: str
    position: int
    offers: tuple[StreamOffer, ...]


class KeitaroClient:
    def __init__(self, config: Settings = settings) -> None:
        self._base_url = config.keitaro_base_url.rstrip("/")
        self._api_key = config.keitaro_api_key

    def offer(self, offer_id: int) -> KeitaroOffer:
        item = self._get(f"/admin_api/v1/offers/{offer_id}")
        return KeitaroOffer(id=item["id"], name=item["name"])

    def search_offers(self, query: str) -> list[KeitaroOffer]:
        needle = query.casefold()
        found = []
        for item in self._get("/admin_api/v1/offers"):
            offer = KeitaroOffer(id=item["id"], name=item["name"])
            if needle in str(offer.id) or needle in offer.name.casefold():
                found.append(offer)
        return found

    def find_domain(self, name: str) -> DirectoryItem | None:
        expected = _host(name)
        for item in self._get("/admin_api/v1/domains"):
            if _host(str(item["name"])) == expected:
                return DirectoryItem(id=item["id"], name=item["name"])
        return None

    def find_group(self, name: str) -> DirectoryItem | None:
        return self._find_by_name(self._get("/admin_api/v1/groups?type=campaigns"), name)

    def find_source(self, name: str) -> DirectoryItem | None:
        return self._find_by_name(self._get("/admin_api/v1/traffic_sources"), name)

    def campaign_name(self, campaign_id: int) -> str:
        campaign = self._get(f"/admin_api/v1/campaigns/{campaign_id}")
        return campaign["name"]

    def streams(self, campaign_id: int) -> list[CampaignStream]:
        payload = self._get(f"/admin_api/v1/campaigns/{campaign_id}/streams")
        streams = []
        for item in payload:
            offers = tuple(
                StreamOffer(offer_id=offer["offer_id"], share=offer["share"])
                for offer in item.get("offers") or []
            )
            streams.append(
                CampaignStream(
                    id=item["id"],
                    name=item["name"],
                    position=item["position"],
                    offers=offers,
                )
            )
        return streams

    def replace_stream_offers(self, stream_id: int, offers: list[dict]) -> None:
        current = self._get(f"/admin_api/v1/streams/{stream_id}")
        body = {
            "campaign_id": current["campaign_id"],
            "name": current["name"],
            "type": current["type"],
            "schema": current["schema"],
            "action_type": current["action_type"],
            "action_payload": current["action_payload"],
            "position": current["position"],
            "state": current["state"],
            "collect_clicks": current["collect_clicks"],
            "filter_or": current["filter_or"],
            "offer_selection": current["offer_selection"],
            "weight": current["weight"],
            "filters": current.get("filters") or [],
            "landings": current.get("landings") or [],
            "triggers": current.get("triggers") or [],
            "offers": [
                {
                    "offer_id": item["offer_id"],
                    "share": item["share"],
                    "state": "active",
                }
                for item in offers
            ],
        }
        if "action_options" in current:
            body["action_options"] = current["action_options"]
        if "comments" in current:
            body["comments"] = current["comments"]
        self._request("PUT", f"/admin_api/v1/streams/{stream_id}", body)

    def create_campaign(
        self,
        name: str,
        countries: list[str],
        offer_id: int,
    ) -> tuple[int, list[CampaignStream]]:
        domain = self.find_domain(settings.keitaro_domain_name)
        group = self.find_group(settings.keitaro_group_name)
        source = self.find_source(settings.keitaro_source_name)
        missing = [
            title
            for title, item in (
                ("домен", domain),
                ("группа", group),
                ("источник", source),
            )
            if item is None
        ]
        if missing:
            raise KeitaroError("В Keitaro не найдены: " + ", ".join(missing))

        campaign = self._request(
            "POST",
            "/admin_api/v1/campaigns",
            {
                "name": name,
                "alias": name,
                "type": "position",
                "domain_id": domain.id,
                "group_id": group.id,
                "traffic_source_id": source.id,
                "cost_type": "CPC",
                "cost_value": 0,
                "cost_currency": "USD",
                "cost_auto": True,
                "state": "active",
                "uniqueness_method": "ip_ua",
            },
        )
        campaign_id = campaign["id"]
        self._request(
            "POST",
            "/admin_api/v1/streams",
            {
                "campaign_id": campaign_id,
                "name": f"{','.join(countries)} -> Google",
                "type": "regular",
                "schema": "redirect",
                "action_type": "http",
                "action_payload": "https://google.com",
                "position": 1,
                "state": "active",
                "collect_clicks": True,
                "filter_or": False,
                "offer_selection": "before_click",
                "weight": 0,
                "filters": [{"name": "country", "mode": "accept", "payload": countries}],
                "offers": [],
            },
        )
        self._request(
            "POST",
            "/admin_api/v1/streams",
            {
                "campaign_id": campaign_id,
                "name": "Offers",
                "type": "regular",
                "schema": "landings",
                "action_type": "http",
                "action_payload": "",
                "position": 2,
                "state": "active",
                "collect_clicks": True,
                "filter_or": False,
                "offer_selection": "before_click",
                "weight": 0,
                "filters": [],
                "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
            },
        )
        return campaign_id, self.streams(campaign_id)

    def _find_by_name(self, items: list[dict], name: str) -> DirectoryItem | None:
        expected = name.rstrip("/").casefold()
        for item in items:
            current = str(item["name"]).rstrip("/").casefold()
            if current == expected:
                return DirectoryItem(id=item["id"], name=item["name"])
        return None

    def _get(self, path: str) -> dict | list:
        return self._request("GET", path)

    def _request(self, method: str, path: str, body: dict | None = None) -> dict | list:
        if not self._api_key:
            raise KeitaroError("В .env не задан KEITARO_API_KEY")

        payload = None
        headers = {
            "Api-Key": self._api_key,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            self._base_url + path,
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise KeitaroError(f"Keitaro ответил {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise KeitaroError(f"Нет соединения с Keitaro: {error.reason}") from error


def _host(value: str) -> str:
    host = value.strip().rstrip("/").casefold()
    if "://" in host:
        host = host.split("://", 1)[1]
    return host
