from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import heatmap


def _poly(
    apn: str,
    west: float,
    south: float,
    east: float,
    north: float,
    attrs: dict | None = None,
) -> dict:
    oid = int("".join(ch for ch in str(apn) if ch.isdigit()) or "1")
    attributes = {"OBJECTID": oid, "APN": apn, "PARCELID": apn}
    attributes.update(attrs or {})
    return {
        "attributes": attributes,
        "geometry": {
            "rings": [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]],
        },
    }


def _zoning(west: float, south: float, east: float, north: float, code: str) -> dict:
    return _poly(
        f"zone-{code}",
        west,
        south,
        east,
        north,
        {"ZONING": code, "ZONINGABBREV": code, "PDUSE": "", "DEVELOPEDASPD": "", "NOTES": ""},
    )


def _general_plan(west: float, south: float, east: float, north: float) -> dict:
    return _poly(
        "gp",
        west,
        south,
        east,
        north,
        {"GPDESIGNATION": "Residential Neighborhood", "GPABBREVIATION": "RN"},
    )


def _permit(apn: str, work: str, *, final: bool = False) -> dict:
    return {
        "attributes": {
            "APN": apn,
            "WORKDESC": work,
            "SUBDESC": "",
            "FINALDATE": 1700000000000 if final else None,
        },
    }


class HeatmapServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_planned_development_text_uses_phrase_boundaries(self):
        self.assertTrue(heatmap._is_residential_pd({
            "PDUSE": "Residential units with structured parking",
            "DEVELOPEDASPD": "",
            "NOTES": "",
        }))
        self.assertFalse(heatmap._is_residential_pd({
            "PDUSE": "Public park",
            "DEVELOPEDASPD": "",
            "NOTES": "",
        }))

    async def test_scores_eligible_residential_parcels_and_skips_finalized_adu(self):
        parcels = [
            _poly("1001", -121.9000, 37.3300, -121.8990, 37.3310),
            _poly("1002", -121.8988, 37.3300, -121.8978, 37.3310),
        ]
        buildings = [
            _poly("9001", -121.8998, 37.3302, -121.8992, 37.3308),
            _poly("9002", -121.8986, 37.3302, -121.8980, 37.3308),
        ]
        expired = [_permit("1002", "Accessory dwelling unit", final=True)]
        zoning = [_zoning(-121.91, 37.32, -121.89, 37.34, "R-1-8")]
        gp = [_general_plan(-121.91, 37.32, -121.89, 37.34)]

        async def fake_query(_client, url, **_kwargs):
            if url == heatmap.PARCELS_URL:
                return parcels
            if url == heatmap.BUILDINGS_URL:
                return buildings
            if url == heatmap.PERMITS_EXPIRED_URL:
                return expired
            if url == heatmap.SAN_JOSE_ZONING_QUERY_URL:
                return zoning
            if url == heatmap.SAN_JOSE_GENERAL_PLAN_QUERY_URL:
                return gp
            return []

        with patch("app.services.heatmap.arcgis.query_features", new=fake_query):
            leads = await heatmap.get_heatmap_data(None, -121.91, 37.32, -121.89, 37.34)

        self.assertEqual({lead["apn"] for lead in leads}, {"1001"})
        lead = leads[0]
        self.assertGreater(lead["score"], 0)
        self.assertLess(lead["opportunity_score"], 40)
        self.assertEqual(lead["lead_status"], "qualified")
        self.assertEqual(lead["score_breakdown"]["opportunity"]["max"], 40.0)
        self.assertIn("components", lead["score_breakdown"]["physical"])
        self.assertIn(lead["confidence"]["level"], {"high", "medium", "low"})
        self.assertEqual(lead["zoning"], "R-1-8")
        self.assertEqual(lead["zoning_ordinance"]["zoning_code"], "R-1-8")
        self.assertIn("20.80.175", " ".join(lead["zoning_ordinance"]["adu_sections"]))
        self.assertIn("geometry", lead)

        with patch("app.services.heatmap.arcgis.query_features", new=fake_query):
            audit_leads = await heatmap.get_heatmap_data(
                None,
                -121.91,
                37.32,
                -121.89,
                37.34,
                include_excluded=True,
            )

        audit_by_apn = {lead["apn"]: lead for lead in audit_leads}
        self.assertEqual(audit_by_apn["1002"]["lead_status"], "excluded")
        self.assertEqual(audit_by_apn["1002"]["score"], 0)
        self.assertEqual(audit_by_apn["1002"]["opportunity_score"], 0)
        self.assertIn("Finalized ADU permit", audit_by_apn["1002"]["exclusion_reason"])

    async def test_paginates_parcels_instead_of_returning_first_page_only(self):
        parcels = [
            _poly("2001", -121.9000, 37.3300, -121.8990, 37.3310),
            _poly("2002", -121.8988, 37.3300, -121.8978, 37.3310),
        ]
        buildings = [
            _poly("9101", -121.8998, 37.3302, -121.8992, 37.3308),
            _poly("9102", -121.8986, 37.3302, -121.8980, 37.3308),
        ]
        zoning = [_zoning(-121.91, 37.32, -121.89, 37.34, "R-1-8")]
        gp = [_general_plan(-121.91, 37.32, -121.89, 37.34)]

        async def fake_query(_client, url, **kwargs):
            offset = int(kwargs.get("result_offset") or 0)
            if url == heatmap.PARCELS_URL:
                return parcels[offset:offset + 1]
            if url == heatmap.BUILDINGS_URL:
                return buildings[offset:offset + 1]
            if url == heatmap.SAN_JOSE_ZONING_QUERY_URL:
                return zoning[offset:offset + 1]
            if url == heatmap.SAN_JOSE_GENERAL_PLAN_QUERY_URL:
                return gp[offset:offset + 1]
            return []

        with (
            patch.object(heatmap, "ARCGIS_PAGE_SIZE", 1),
            patch("app.services.heatmap.arcgis.query_features", new=fake_query),
        ):
            leads = await heatmap.get_heatmap_data(None, -121.91, 37.32, -121.89, 37.34)

        self.assertEqual([lead["apn"] for lead in sorted(leads, key=lambda l: l["apn"])], ["2001", "2002"])

    async def test_boundary_geometry_filters_parcels_inside_bbox(self):
        parcels = [
            _poly("2501", -121.9000, 37.3300, -121.8990, 37.3310),
            _poly("2502", -121.8975, 37.3300, -121.8965, 37.3310),
        ]
        buildings = [
            _poly("9251", -121.8998, 37.3302, -121.8992, 37.3308),
            _poly("9252", -121.8973, 37.3302, -121.8967, 37.3308),
        ]
        zoning = [_zoning(-121.91, 37.32, -121.89, 37.34, "R-1-8")]
        gp = [_general_plan(-121.91, 37.32, -121.89, 37.34)]
        boundary = {
            "type": "Polygon",
            "coordinates": [[
                [-121.901, 37.329],
                [-121.8985, 37.329],
                [-121.8985, 37.332],
                [-121.901, 37.332],
                [-121.901, 37.329],
            ]],
        }

        async def fake_query(_client, url, **_kwargs):
            if url == heatmap.PARCELS_URL:
                return parcels
            if url == heatmap.BUILDINGS_URL:
                return buildings
            if url == heatmap.SAN_JOSE_ZONING_QUERY_URL:
                return zoning
            if url == heatmap.SAN_JOSE_GENERAL_PLAN_QUERY_URL:
                return gp
            return []

        with patch("app.services.heatmap.arcgis.query_features", new=fake_query):
            leads = await heatmap.get_heatmap_data(
                None,
                -121.91,
                37.32,
                -121.89,
                37.34,
                boundary_geometry=boundary,
            )

        self.assertEqual([lead["apn"] for lead in leads], ["2501"])

    async def test_excludes_non_residential_zoning(self):
        parcels = [_poly("3001", -121.9000, 37.3300, -121.8990, 37.3310)]
        buildings = [_poly("9301", -121.8998, 37.3302, -121.8992, 37.3308)]
        zoning = [_zoning(-121.91, 37.32, -121.89, 37.34, "PQP")]
        # Non-residential GP — both zone code and GP must be non-residential for a
        # hard exclusion; if GP is residential, the parcel surfaces as "verify" instead.
        gp = [_poly("gp", -121.91, 37.32, -121.89, 37.34,
                    {"GPDESIGNATION": "Heavy Industrial", "GPABBREVIATION": "HI"})]

        async def fake_query(_client, url, **_kwargs):
            if url == heatmap.PARCELS_URL:
                return parcels
            if url == heatmap.BUILDINGS_URL:
                return buildings
            if url == heatmap.SAN_JOSE_ZONING_QUERY_URL:
                return zoning
            if url == heatmap.SAN_JOSE_GENERAL_PLAN_QUERY_URL:
                return gp
            return []

        with patch("app.services.heatmap.arcgis.query_features", new=fake_query):
            leads = await heatmap.get_heatmap_data(None, -121.91, 37.32, -121.89, 37.34)

        self.assertEqual(leads, [])

    async def test_include_excluded_returns_audit_record_without_target_score(self):
        parcels = [_poly("3101", -121.9000, 37.3300, -121.8990, 37.3310)]
        buildings = [_poly("9311", -121.8998, 37.3302, -121.8992, 37.3308)]
        zoning = [_zoning(-121.91, 37.32, -121.89, 37.34, "PQP")]
        gp = [_poly("gp", -121.91, 37.32, -121.89, 37.34,
                    {"GPDESIGNATION": "Heavy Industrial", "GPABBREVIATION": "HI"})]

        async def fake_query(_client, url, **_kwargs):
            if url == heatmap.PARCELS_URL:
                return parcels
            if url == heatmap.BUILDINGS_URL:
                return buildings
            if url == heatmap.SAN_JOSE_ZONING_QUERY_URL:
                return zoning
            if url == heatmap.SAN_JOSE_GENERAL_PLAN_QUERY_URL:
                return gp
            return []

        with patch("app.services.heatmap.arcgis.query_features", new=fake_query):
            leads = await heatmap.get_heatmap_data(
                None,
                -121.91,
                37.32,
                -121.89,
                37.34,
                include_excluded=True,
            )

        self.assertEqual(len(leads), 1)
        lead = leads[0]
        self.assertEqual(lead["lead_status"], "excluded")
        self.assertEqual(lead["score"], 0)
        self.assertEqual(lead["opportunity_score"], 0)
        self.assertEqual(lead["score_breakdown"]["opportunity"]["score"], 0)
        self.assertEqual(
            lead["score_breakdown"]["opportunity"]["components"][0]["label"],
            "Qualification gate",
        )
        self.assertIn("Non-residential zoning excluded: PQP", lead["exclusion_reason"])

    async def test_opportunity_score_varies_with_permit_status(self):
        parcels = [
            _poly("4001", -121.9000, 37.3300, -121.8990, 37.3310),
            _poly("4002", -121.8988, 37.3300, -121.8978, 37.3310),
        ]
        buildings = [
            _poly("9401", -121.8998, 37.3302, -121.8992, 37.3308),
            _poly("9402", -121.8986, 37.3302, -121.8980, 37.3308),
        ]
        expired = [_permit("4002", "Accessory dwelling unit")]
        zoning = [_zoning(-121.91, 37.32, -121.89, 37.34, "R-1-8")]
        gp = [_general_plan(-121.91, 37.32, -121.89, 37.34)]

        async def fake_query(_client, url, **_kwargs):
            if url == heatmap.PARCELS_URL:
                return parcels
            if url == heatmap.BUILDINGS_URL:
                return buildings
            if url == heatmap.PERMITS_EXPIRED_URL:
                return expired
            if url == heatmap.SAN_JOSE_ZONING_QUERY_URL:
                return zoning
            if url == heatmap.SAN_JOSE_GENERAL_PLAN_QUERY_URL:
                return gp
            return []

        with patch("app.services.heatmap.arcgis.query_features", new=fake_query):
            leads = await heatmap.get_heatmap_data(None, -121.91, 37.32, -121.89, 37.34)

        by_apn = {lead["apn"]: lead for lead in leads}
        self.assertGreater(by_apn["4001"]["opportunity_score"], by_apn["4002"]["opportunity_score"])
        self.assertLessEqual(by_apn["4001"]["opportunity_score"], 40)


if __name__ == "__main__":
    unittest.main()
