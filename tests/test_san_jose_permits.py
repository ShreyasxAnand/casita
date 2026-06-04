from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import main
from app.cities.san_jose import permits
from app.cities.san_jose.permits import PermitRecord
from app.result import FetchResult


def _permit(work: str, *, sub: str = "", final: bool = False) -> dict:
    return {
        "attributes": {
            "FOLDERNUM": work[:8],
            "WORKDESC": work,
            "SUBDESC": sub,
            "ISSUEDATE": 1700000000000,
            "FINALDATE": 1701000000000 if final else None,
        },
    }


class SanJosePermitsTest(unittest.IsolatedAsyncioTestCase):
    def test_adu_text_detector_matches_terms_not_arbitrary_substrings(self):
        self.assertTrue(permits.is_adu_permit_text("New detached ADU"))
        self.assertTrue(permits.is_adu_permit_text("Two detached ADUs"))
        self.assertTrue(permits.is_adu_permit_text("Junior accessory dwelling conversion"))
        self.assertTrue(permits.is_adu_permit_text("A.D.U. garage conversion"))
        self.assertFalse(permits.is_adu_permit_text("Bathroom remodel"))
        self.assertFalse(permits.is_adu_permit_text("Gradual foundation repair"))

    async def test_fetch_adu_permits_filters_live_apn_records(self):
        where_clauses = []

        async def fake_fetch(_client, url, params, *, stage):
            where_clauses.append(params["where"])
            if "/8/query" in url:
                return {"features": [
                    _permit("New detached ADU"),
                    _permit("Kitchen remodel"),
                ]}
            return {"features": [
                _permit("JADU conversion", final=True),
                _permit("Swimming pool demolition", final=True),
            ]}

        with patch("app.cities.san_jose.permits.arcgis.fetch_json", new=fake_fetch):
            result = await permits.fetch_adu_permits(None, "123-456-78")

        self.assertTrue(result.is_ok)
        self.assertEqual(set(where_clauses), {"APN = '12345678'"})
        self.assertEqual([record.work_desc for record in result.data], ["New detached ADU", "JADU conversion"])
        self.assertEqual(result.data[1].final_date, "2023-11-26")

    async def test_heatmap_adu_permit_endpoint_sanitizes_and_serializes_apn(self):
        async def fake_fetch_adu_permits(_client, apn):
            self.assertEqual(apn, "12345678")
            return FetchResult.ok(
                [
                    PermitRecord(
                        folder_num="B123",
                        work_desc="New detached ADU",
                        sub_desc="",
                        status="expired",
                        issue_date="2023-01-01",
                        final_date="2023-06-01",
                    ),
                ],
                "test source",
            )

        main.app.state.http_client = None
        with patch("app.main.fetch_adu_permits", new=fake_fetch_adu_permits):
            payload = await main.get_heatmap_lead_adu_permits("123-456-78")

        self.assertEqual(payload["apn"], "12345678")
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["finalized_count"], 1)
        self.assertEqual(payload["records"][0]["folder_num"], "B123")

    async def test_heatmap_adu_permit_endpoint_keeps_failed_lookup_unknown(self):
        async def fake_fetch_adu_permits(_client, apn):
            return FetchResult.failed("permit service timeout", "test source")

        main.app.state.http_client = None
        with patch("app.main.fetch_adu_permits", new=fake_fetch_adu_permits):
            payload = await main.get_heatmap_lead_adu_permits("123-456-78")

        self.assertEqual(payload["status"], "failed")
        self.assertIsNone(payload["exists"])
        self.assertIsNone(payload["active_count"])
        self.assertEqual(payload["records"], [])


if __name__ == "__main__":
    unittest.main()
