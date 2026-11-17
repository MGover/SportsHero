import re
import unicodedata
from difflib import SequenceMatcher
from typing import Callable, Iterable, TypeVar


T = TypeVar("T")

SACRAMENTO_AFFILIATE_CALLSIGNS = {
    "KOVR": "CBS Sacramento",
    "KXTV": "ABC Sacramento",
    "KCRA": "NBC Sacramento",
    "KTXL": "FOX Sacramento",
}

EPG_CHANNEL_QUERY_ALIASES = {
    "nfl network": "NFLNetwork.us",
    "nfl redzone": "NFLRedZone.us",
    "nfl red zone": "US-NFL Red Zone",
}


def normalize_search_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def score_search_match(query: str, candidate: object) -> float:
    normalized_query = normalize_search_text(query)
    normalized_candidate = normalize_search_text(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0

    query_tokens = normalized_query.split()
    candidate_tokens = normalized_candidate.split()
    token_scores = []
    for query_token in query_tokens:
        best = 0.0
        for candidate_token in candidate_tokens:
            if query_token == candidate_token:
                best = 1.0
                break
            if len(query_token) >= 4 and len(candidate_token) >= 4:
                best = max(best, SequenceMatcher(None, query_token, candidate_token).ratio())
        token_scores.append(best if best >= 0.82 else 0.0)

    token_coverage = sum(token_scores) / len(token_scores)
    if token_coverage == 0:
        return 0.0

    phrase_match = normalized_query in normalized_candidate
    compact_similarity = SequenceMatcher(
        None,
        normalized_query.replace(" ", ""),
        normalized_candidate.replace(" ", ""),
    ).ratio()
    candidate_precision = sum(score > 0 for score in token_scores) / len(candidate_tokens)
    return 0.72 * token_coverage + 0.16 * phrase_match + 0.08 * compact_similarity + 0.04 * candidate_precision


def rank_search_matches(
    query: str,
    records: Iterable[T],
    get_candidate: Callable[[T], object],
    limit: int = 25,
    minimum_score: float = 0.0,
) -> list[tuple[float, T]]:
    if not normalize_search_text(query):
        return []

    matches = []
    for record in records:
        candidate = get_candidate(record)
        score = score_search_match(query, candidate)
        if score >= minimum_score:
            matches.append((score, str(candidate), record))

    matches.sort(key=lambda item: (-item[0], len(normalize_search_text(item[1])), normalize_search_text(item[1])))
    return [(score, record) for score, _, record in matches[:limit]]


def rank_catalog_channels(query: str, records: Iterable[dict], limit: int = 25, minimum_score: float = 0.0):
    if not normalize_search_text(query):
        return []

    matches = []
    for record in records:
        display_name = str(record.get("name") or "")
        search_fields = [
            display_name,
            str(record.get("epg_channel_id") or ""),
            str(record.get("custom_sid") or ""),
        ]
        normalized_metadata = normalize_search_text(" ".join(search_fields))
        metadata_tokens = set(normalized_metadata.split())
        for callsign, alias in SACRAMENTO_AFFILIATE_CALLSIGNS.items():
            if callsign.casefold() in metadata_tokens:
                search_fields.append(alias)
        preferred_epg_id = EPG_CHANNEL_QUERY_ALIASES.get(normalize_search_text(query))
        if preferred_epg_id and str(record.get("epg_channel_id") or "").casefold() == preferred_epg_id.casefold():
            search_fields.append(query)

        score = max((score_search_match(query, field) for field in search_fields), default=0.0)
        if score >= minimum_score:
            matches.append((score, display_name, record))

    matches.sort(key=lambda item: (-item[0], len(normalize_search_text(item[1])), normalize_search_text(item[1])))
    return [(score, record) for score, _, record in matches[:limit]]