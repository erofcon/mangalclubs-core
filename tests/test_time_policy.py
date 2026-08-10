import unittest
from datetime import datetime, timezone

from app.schemas.auth import OtpRequested
from app.schemas.order import OrderCreateIn, OrderStatusOut
from app.services.orders import format_iiko_datetime


class MoscowTimePolicyTests(unittest.TestCase):
    def test_order_time_uses_moscow_wall_clock_not_client_offset(self):
        order = OrderCreateIn.model_validate(
            {
                "orderType": "pickup",
                "organizationSlug": "grozny",
                "phone": "+79990000000",
                # A misconfigured client timezone must not shift a restaurant
                # time selected as 18:30.
                "completeBefore": "2030-01-15T18:30:00-05:00",
                "items": [{"productId": "item", "amount": 1}],
            }
        )

        self.assertEqual(order.complete_before.isoformat(), "2030-01-15T18:30:00+03:00")
        self.assertEqual(format_iiko_datetime(order.complete_before), "2030-01-15 18:30:00.000")

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


if __name__ == "__main__":
    unittest.main()
