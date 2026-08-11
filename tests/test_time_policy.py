import unittest
from datetime import datetime, time, timezone
from types import SimpleNamespace
from uuid import UUID

from app.core.time import MOSCOW_TZ
from app.models.organization import OrganizationWorkingHour
from app.schemas.auth import OtpRequested
from app.schemas.order import OrderCreateIn, OrderStatusOut
from app.services.availability import get_organization_order_time_slots
from app.services.orders import format_iiko_datetime


class MoscowTimePolicyTests(unittest.TestCase):
    def test_order_time_converts_client_instant_to_moscow(self):
        order = OrderCreateIn.model_validate(
            {
                "orderType": "pickup",
                "organizationSlug": "grozny",
                "phone": "+79990000000",
                # 15:30 UTC is the canonical representation of 18:30 Moscow.
                "completeBefore": "2030-01-15T15:30:00.000Z",
                "items": [{"productId": "item", "amount": 1}],
            }
        )

        self.assertEqual(order.complete_before.isoformat(), "2030-01-15T18:30:00+03:00")
        self.assertEqual(format_iiko_datetime(order.complete_before), "2030-01-15 18:30:00.000")

    def test_naive_order_time_is_interpreted_as_moscow(self):
        order = OrderCreateIn.model_validate(
            {
                "orderType": "pickup",
                "organizationSlug": "grozny",
                "phone": "+79990000000",
                "completeBefore": "2030-01-15T18:30:00",
                "items": [{"productId": "item", "amount": 1}],
            }
        )

        self.assertEqual(order.complete_before.isoformat(), "2030-01-15T18:30:00+03:00")

    def test_iiko_datetime_converts_utc_to_moscow_even_across_date_boundary(self):
        self.assertEqual(
            format_iiko_datetime(datetime(2030, 1, 15, 23, 30, tzinfo=timezone.utc)),
            "2030-01-16 02:30:00.000",
        )

    def test_api_datetime_is_serialized_in_moscow(self):
        payload = OtpRequested(resend_available_at=datetime(2030, 1, 1, tzinfo=timezone.utc))

        self.assertIn("2030-01-01T03:00:00+03:00", payload.model_dump_json())

    def test_iiko_status_time_is_exposed_with_moscow_offset(self):
        status = OrderStatusOut.model_validate(
            {
                "organization_id": "00000000-0000-0000-0000-000000000001",
                "organization_slug": "grozny",
                "iiko_organization_id": "iiko-org",
                "complete_before": "2030-01-15 18:30:00.000",
                "should_notify_customer": False,
            }
        )

        self.assertIn("2030-01-15T18:30:00+03:00", status.model_dump_json())

    def test_today_slots_exclude_times_without_enough_payment_time(self):
        now = datetime(2030, 1, 15, 14, 56, tzinfo=MOSCOW_TZ)
        working_hour = OrganizationWorkingHour(
            weekday=now.weekday(),
            is_closed=False,
            opens_at=time(10, 0),
            closes_at=time(20, 0),
        )
        organization = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            slug="grozny",
            working_hours=[working_hour],
        )

        schedule = get_organization_order_time_slots(organization, now=now)
        starts_at = [slot["starts_at"] for slot in schedule["slots"]]

        self.assertNotIn(now.replace(hour=15, minute=0), starts_at)
        self.assertEqual(starts_at[0], now.replace(hour=15, minute=30))


if __name__ == "__main__":
    unittest.main()
