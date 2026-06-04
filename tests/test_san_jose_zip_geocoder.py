from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cities.san_jose.geocoder import geocode_zip_extent


class SanJoseZipGeocoderTest(unittest.IsolatedAsyncioTestCase):
    async def test_selects_san_jose_zip_candidate_with_extent(self):
        async def fake_fetch(*_args, **_kwargs):
            return {
                "candidates": [
                    {
                        "attributes": {"Postal": "95129", "Region": "CA"},
                        "location": {"x": -122.20, "y": 37.31},
                        "extent": {
                            "xmin": -122.21, "ymin": 37.30,
                            "xmax": -122.19, "ymax": 37.32,
                        },
                    },
                    {
                        "attributes": {"Postal": "95129", "Region": "CA"},
                        "location": {"x": -122.00, "y": 37.30},
                        "extent": {
                            "xmin": -122.04, "ymin": 37.28,
                            "xmax": -121.95, "ymax": 37.33,
                        },
                    },
                ],
            }

        with patch("app.cities.san_jose.geocoder.fetch_json", new=fake_fetch):
            extent = await geocode_zip_extent(None, "95129")

        self.assertEqual(extent["zip"], "95129")
        self.assertEqual(extent["center_lon"], -122.00)
        self.assertEqual(extent["west"], -122.04)
        self.assertEqual(extent["east"], -121.95)

    async def test_rejects_zip_without_san_jose_candidate(self):
        async def fake_fetch(*_args, **_kwargs):
            return {
                "candidates": [{
                    "attributes": {"Postal": "90210", "Region": "CA"},
                    "location": {"x": -118.40, "y": 34.09},
                    "extent": {
                        "xmin": -118.43, "ymin": 34.06,
                        "xmax": -118.37, "ymax": 34.12,
                    },
                }],
            }

        with patch("app.cities.san_jose.geocoder.fetch_json", new=fake_fetch):
            with self.assertRaises(HTTPException) as ctx:
                await geocode_zip_extent(None, "90210")

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
