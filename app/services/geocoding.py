from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)

GEOAPIFY_REVERSE_GEOCODING_URL = "https://api.geoapify.com/v1/geocode/reverse"


async def resolve_address_for_coordinates(*, latitude: float, longitude: float) -> dict[str, Any] | None:
    if not settings.geoapify_api_key:
        return None

    try:
        data = await request_geoapify_reverse_geocoding(latitude=latitude, longitude=longitude)
    except GeoapifyGeocodingError as exc:
        logger.warning("Geoapify reverse geocoding failed for %s,%s: %s", latitude, longitude, exc)
        return None

    properties = first_geoapify_feature_properties(data)
    if properties is None:
        return None

    return build_resolved_address(properties)


async def request_geoapify_reverse_geocoding(*, latitude: float, longitude: float) -> dict[str, Any]:
    timeout = httpx.Timeout(settings.geoapify_request_timeout_seconds)
    params = {
        "lat": latitude,
        "lon": longitude,
        "lang": "ru",
        "apiKey": settings.geoapify_api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(GEOAPIFY_REVERSE_GEOCODING_URL, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise GeoapifyGeocodingError(f"HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise GeoapifyGeocodingError(str(exc)) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise GeoapifyGeocodingError("Geoapify returned a non-JSON response") from exc

    if not isinstance(data, dict):
        raise GeoapifyGeocodingError("Geoapify returned an invalid response")

    return data


def first_geoapify_feature_properties(data: dict[str, Any]) -> dict[str, Any] | None:
    features = data.get("features")
    if not isinstance(features, list) or not features:
        return None

    feature = features[0]
    if not isinstance(feature, dict):
        return None

    properties = feature.get("properties")
    return properties if isinstance(properties, dict) else None


def build_resolved_address(properties: dict[str, Any]) -> dict[str, Any]:
    street = optional_str(properties.get("street") or properties.get("address_line1"))
    house = optional_str(properties.get("housenumber") or properties.get("house_number"))

    return {
        "formatted": optional_str(properties.get("formatted")),
        "country": optional_str(properties.get("country")),
        "country_code": optional_str(properties.get("country_code")),
        "region": optional_str(properties.get("state") or properties.get("region")),
        "city": optional_str(properties.get("city") or properties.get("town") or properties.get("village")),
        "district": optional_str(properties.get("district") or properties.get("county")),
        "suburb": optional_str(properties.get("suburb")),
        "street": street,
        "house": house,
        "postcode": optional_str(properties.get("postcode")),
        "place_id": optional_str(properties.get("place_id")),
        "source": "geoapify",
    }


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


class GeoapifyGeocodingError(Exception):
    pass
