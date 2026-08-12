import unittest
from decimal import Decimal

from app.schemas.delivery import DeliveryZoneCreate
from app.services.delivery import create_delivery_zone


class FakeSession:
    def __init__(self):
        self.added = None

    async def scalar(self, statement):
        return None

    def add(self, value):
        self.added = value

    async def commit(self):
        return None

    async def refresh(self, value):
        return None


class DeliveryZoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_sets_required_compatibility_columns(self):
        db = FakeSession()
        payload = DeliveryZoneCreate(
            distance_from_km=Decimal("0"),
            distance_to_km=Decimal("3"),
            price=200,
            delivery_time="35 minutes",
        )

        zone = await create_delivery_zone(db, payload)

        self.assertIs(db.added, zone)
        self.assertEqual(zone.sort_order, 0)
        self.assertTrue(zone.is_active)


if __name__ == "__main__":
    unittest.main()
