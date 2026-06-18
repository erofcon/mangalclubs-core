from dataclasses import dataclass

import httpx

from app.core.config import settings


class GreenSMSError(RuntimeError):
    pass


@dataclass(frozen=True)
class GreenSMSCallResponse:
    request_id: str
    code: str


def phone_for_greensms(phone: str) -> str:
    return phone.lstrip("+")


async def send_call_verification(phone: str) -> GreenSMSCallResponse:
    if not settings.greensms_auth_token:
        raise GreenSMSError("GreenSMS auth token is not configured")

    payload: dict[str, str] = {
        "to": phone_for_greensms(phone),
        "voice": str(settings.greensms_call_voice).lower(),
        "lang": settings.greensms_call_lang,
    }
    if settings.greensms_call_tag:
        payload["tag"] = settings.greensms_call_tag[:36]

    try:
        async with httpx.AsyncClient(timeout=settings.greensms_request_timeout_seconds) as client:
            response = await client.post(
                settings.greensms_call_send_url,
                data=payload,
                headers={"Authorization": f"Bearer {settings.greensms_auth_token}"},
            )
            if response.status_code not in (200, 301):
                response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise GreenSMSError(f"GreenSMS returned HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise GreenSMSError(f"GreenSMS request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise GreenSMSError("GreenSMS returned invalid JSON") from exc

    request_id = data.get("request_id")
    code = data.get("code")

    if not isinstance(request_id, str) or not request_id:
        raise GreenSMSError("GreenSMS response does not contain request_id")

    if not isinstance(code, str) or len(code) != 4 or not code.isdigit():
        raise GreenSMSError("GreenSMS response does not contain a valid code")

    return GreenSMSCallResponse(request_id=request_id, code=code)
