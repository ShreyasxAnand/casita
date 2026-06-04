from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cities.san_jose.zip_boundaries import fetch_zip_boundary


def _zip_feature(zip_code: str = "95129", san_jose_limits: str = "Yes") -> dict:
    return {
        "attributes": {"ZIPCODE": zip_code, "SANJOSELIMITS": san_jose_limits},
        "geometry": {
            "rings": [[
                [-122.04, 37.28],
                [-121.95, 37.28],
                [-121.95, 37.33],
                [-122.04, 37.33],
                [-122.04, 37.28],
            ]],
        },
    }


class SanJoseZipBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_official_zip_boundary_polygon(self):
        async def fake_fetch(_client, _url, params, *, stage):
            self.assertIn("ZIPCODE = '95129'", params["where"])
            self.assertIn("SANJOSELIMITS = 'Yes'", params["where"])
            self.assertEqual(params["outSR"], "4326")
            return {"features": [_zip_feature()]}

        with patch("app.cities.san_jose.zip_boundaries.arcgis.fetch_json", new=fake_fetch):
            boundary = await fetch_zip_boundary(None, "95129")

        self.assertEqual(boundary["zip"], "95129")
        self.assertEqual(boundary["bbox"]["west"], -122.04)
        self.assertEqual(boundary["bbox"]["east"], -121.95)
        self.assertEqual(boundary["geometry"]["type"], "Polygon")
        self.assertEqual(boundary["source"], "San Jose Zipcode Boundaries layer 181")

    async def test_rejects_zip_without_san_jose_boundary(self):
        async def fake_fetch(*_args, **_kwargs):
            return {"features": []}

        with patch("app.cities.san_jose.zip_boundaries.arcgis.fetch_json", new=fake_fetch):
            with self.assertRaises(HTTPException) as ctx:
                await fetch_zip_boundary(None, "90210")

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
