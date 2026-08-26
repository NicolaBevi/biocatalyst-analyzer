"""Universo di titoli biotech quotati, costruito dai codici SIC della SEC.

Non esiste uno screener gratuito con API stabile (Finviz non ne pubblica
una), quindi l'universo si ricava dall'anagrafica SEC: `browse-edgar` elenca
le società per codice SIC, e `company_tickers_exchange.json` dice quali di
queste hanno un ticker su NASDAQ o NYSE.

Il feed atom di `browse-edgar` ha un difetto noto: il nome della società
finisce in un tag `<last-date>` mal etichettato e il titolo della entry
contiene un artefatto Perl ("ARRAY(0x...)"). Si estrae quindi il solo CIK,
che è affidabile, e il nome arriva dalla mappatura dei ticker.
"""

from __future__ import annotations

from typing import ClassVar
from xml.etree import ElementTree as ET

from biocatalyst.data.base import DataParseError, HTTPDataProvider, RateLimiter
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger

logger = get_logger(__name__)

BROWSE_EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

#: 2836 = Biological Products, 8731 = Commercial Physical & Biological Research.
#: Insieme danno ~175 società quotate: l'universo dei biotech clinical-stage.
#: 2834 (Pharmaceutical Preparations) ne aggiungerebbe oltre 1.500, in larga
#: parte big pharma fuori dal profilo micro-cap cercato, moltiplicando i tempi.
DEFAULT_SIC_CODES: tuple[str, ...] = ("2836", "8731")
PHARMA_SIC_CODE = "2834"

LISTED_EXCHANGES = frozenset({"NASDAQ", "NYSE"})

#: browse-edgar pagina a 100 risultati; il limite evita cicli infiniti se la
#: paginazione cambiasse comportamento.
PAGE_SIZE = 100
MAX_PAGES = 30


class UniverseProvider(HTTPDataProvider):
    """Elenco di ticker biotech quotati su NASDAQ/NYSE."""

    rate_limiter: ClassVar[RateLimiter] = RateLimiter(0.12)

    def __init__(
        self,
        user_agent: str,
        cache: DataCache | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        ttl_seconds: int = 86_400,
    ) -> None:
        super().__init__(
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            headers={"User-Agent": user_agent},
        )
        self.ttl_seconds = ttl_seconds

    def get_universe(self, sic_codes: tuple[str, ...] = DEFAULT_SIC_CODES) -> dict[str, str]:
        """Mappa ticker -> ragione sociale per le società dei SIC richiesti.

        Solo società con un ticker su NASDAQ o NYSE: l'anagrafica SEC include
        anche società non quotate e veicoli societari senza titolo scambiato.
        """
        cik_set: set[str] = set()
        for sic in sic_codes:
            cik_set |= self._ciks_for_sic(sic)

        listed = self._listed_companies()
        universe = {listed[cik][0]: listed[cik][1] for cik in cik_set if cik in listed}
        logger.info(
            "universo_costruito",
            sic=list(sic_codes),
            aziende_sec=len(cik_set),
            quotate=len(universe),
        )
        return universe

    def _ciks_for_sic(self, sic: str) -> set[str]:
        collected: set[str] = set()
        start = 0
        for _ in range(MAX_PAGES):
            page = self._ciks_page(sic, start)
            collected |= page
            if len(page) < PAGE_SIZE:
                break
            start += PAGE_SIZE
        return collected

    def _ciks_page(self, sic: str, start: int) -> set[str]:
        payload = self._get_json_or_xml(sic, start)
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise DataParseError(f"feed SEC non interpretabile per SIC {sic}") from exc

        ciks: set[str] = set()
        for entry in root.findall(".//a:entry", ATOM_NS):
            node = entry.find("a:content/a:company-info/a:cik", ATOM_NS)
            if node is not None and node.text:
                ciks.add(node.text.strip())
        return ciks

    def _get_json_or_xml(self, sic: str, start: int) -> bytes:
        """Il feed è XML, non JSON: si usa il livello HTTP di base con cache propria."""
        cache_key = f"sec:universe:{sic}:{start}"

        def fetch() -> str:
            self.rate_limiter.wait()
            import httpx

            from biocatalyst.data.base import DataUnavailableError

            try:
                response = httpx.get(
                    BROWSE_EDGAR_URL,
                    params={
                        "action": "getcompany",
                        "SIC": sic,
                        "owner": "include",
                        "count": str(PAGE_SIZE),
                        "start": str(start),
                        "output": "atom",
                    },
                    headers=self.headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                )
            except httpx.TimeoutException as exc:
                raise DataUnavailableError(f"timeout sull'elenco SIC {sic}") from exc
            except httpx.TransportError as exc:
                raise DataUnavailableError(f"errore di rete sull'elenco SIC {sic}: {exc}") from exc
            if response.status_code >= 400:
                raise DataUnavailableError(
                    f"errore HTTP {response.status_code} sull'elenco SIC {sic}"
                )
            return response.text

        if self.cache is None:
            return fetch().encode()
        return self.cache.get_or_fetch(cache_key, self.ttl_seconds, fetch).encode()

    def _listed_companies(self) -> dict[str, tuple[str, str]]:
        """CIK zero-paddato -> (ticker, ragione sociale) per i soli titoli quotati."""
        payload = self._get_json(
            TICKERS_EXCHANGE_URL,
            ttl_seconds=self.ttl_seconds,
            cache_key="sec:tickers_exchange",
        )
        fields = payload.get("fields", [])
        try:
            i_cik = fields.index("cik")
            i_name = fields.index("name")
            i_ticker = fields.index("ticker")
            i_exchange = fields.index("exchange")
        except ValueError as exc:
            raise DataParseError(
                f"struttura inattesa in company_tickers_exchange.json: campi {fields}"
            ) from exc

        listed: dict[str, tuple[str, str]] = {}
        for row in payload.get("data", []):
            exchange = (row[i_exchange] or "").upper()
            ticker = row[i_ticker]
            if exchange not in LISTED_EXCHANGES or not ticker:
                continue
            listed[f"{int(row[i_cik]):010d}"] = (ticker, row[i_name])
        return listed
