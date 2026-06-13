from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.organization import Organization


class TBankError(Exception):
    pass


@dataclass(frozen=True)
class TBankCredentials:
    terminal_key: str
    password: str


TERMINAL_PAYMENT_STATUSES = {
    "REJECTED": "payment_failed",
    "CANCELED": "payment_cancelled",
    "DEADLINE_EXPIRED": "payment_expired",
    "REVERSED": "payment_cancelled",
    "REFUNDED": "payment_cancelled",
    "PARTIAL_REFUNDED": "payment_cancelled",
}


def get_tbank_credentials(organization: Organization) -> TBankCredentials:
    terminal_key = organization.tbank_terminal_key or settings.tbank_default_terminal_key
    password = organization.tbank_password or settings.tbank_default_password
    if not terminal_key or not password:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "T-Bank acquiring is not configured")

    return TBankCredentials(terminal_key=terminal_key, password=password)


def tbank_token(payload: dict[str, Any], password: str) -> str:
    values: dict[str, Any] = {"Password": password}
    for key, value in payload.items():
        if key == "Token" or isinstance(value, (dict, list, tuple)):
            continue
        if value is None:
            continue
        values[key] = value

    token_source = "".join(stringify_token_value(values[key]) for key in sorted(values))
    return hashlib.sha256(token_source.encode("utf-8")).hexdigest()


def verify_tbank_token(payload: dict[str, Any], password: str) -> bool:
    token = payload.get("Token")
    if not isinstance(token, str) or not token:
        return False

    expected_token = tbank_token(payload, password)
    return token.lower() == expected_token.lower()


def stringify_token_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def init_tbank_payment(
    *,
    credentials: TBankCredentials,
    amount_kopecks: int,
    bank_order_id: str,
    description: str,
    customer_key: str | None,
    notification_url: str,
    success_url: str | None,
    fail_url: str | None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "TerminalKey": credentials.terminal_key,
        "Amount": amount_kopecks,
        "OrderId": bank_order_id,
        "Description": description[:250],
        "NotificationURL": notification_url,
    }
    if customer_key:
        payload["CustomerKey"] = customer_key
    if success_url:
        payload["SuccessURL"] = success_url
    if fail_url:
        payload["FailURL"] = fail_url
    if data:
        payload["DATA"] = data

    payload["Token"] = tbank_token(payload, credentials.password)
    response_data = await request_tbank_json("Init", payload)

    if response_data.get("Success") is not True:
        message = response_data.get("Message") or response_data.get("Details") or "T-Bank payment init failed"
        raise TBankError(str(message))

    payment_url = response_data.get("PaymentURL")
    payment_id = response_data.get("PaymentId")
    if not isinstance(payment_url, str) or not payment_url:
        raise TBankError("T-Bank did not return PaymentURL")
    if payment_id is not None and not isinstance(payment_id, str):
        response_data["PaymentId"] = str(payment_id)

    return response_data


async def get_tbank_payment_state(
    *,
    credentials: TBankCredentials,
    bank_payment_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "TerminalKey": credentials.terminal_key,
        "PaymentId": bank_payment_id,
    }
    payload["Token"] = tbank_token(payload, credentials.password)
    response_data = await request_tbank_json("GetState", payload)

    if response_data.get("Success") is not True:
        message = response_data.get("Message") or response_data.get("Details") or "T-Bank get state failed"
        raise TBankError(str(message))

    return response_data


async def request_tbank_json(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.tbank_api_base_url.rstrip('/')}/{method.lstrip('/')}"
    timeout = httpx.Timeout(settings.tbank_request_timeout_seconds)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise TBankError(f"T-Bank request failed with HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise TBankError(f"T-Bank request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise TBankError("T-Bank returned a non-JSON response") from exc

    if not isinstance(data, dict):
        raise TBankError("T-Bank returned an invalid response")

    return data


def map_tbank_status(status_value: Any) -> str:
    if not isinstance(status_value, str) or not status_value:
        return "payment_pending"

    status_upper = status_value.upper()
    if status_upper in settings.tbank_paid_status_set:
        return "paid"

    return TERMINAL_PAYMENT_STATUSES.get(status_upper, "payment_form_created")
