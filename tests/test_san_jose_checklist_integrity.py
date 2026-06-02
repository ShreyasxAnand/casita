from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cities.san_jose.checklist import build_checklist
from app.cities.san_jose.code_enforcement import CodeEnforcementData, CodeIssue
from app.cities.san_jose.designations import DesignationData
from app.cities.san_jose.permits import PermitRecord, PermitsData
from app.cities.san_jose.zoning import GeneralPlanData, ZoningData
from app.result import FetchResult


VALID_STATUSES = {"pass", "fail", "verify", "unavailable", "info"}
REQUIRED_KEYS = {"part", "number", "status", "question", "detail", "source"}


@dataclass(frozen=True)
class ChecklistFixture:
    name: str
    address: str
    site_model: dict[str, Any]
    zoning: FetchResult[ZoningData]
    general_plan: FetchResult[GeneralPlanData]
    designations: dict[str, FetchResult[DesignationData]]
    property_stats: dict[str, Any]
    adu_type: str
    permits: FetchResult[PermitsData]
    code_enforcement: FetchResult[CodeEnforcementData]
    expected_count: int
    expected_statuses: dict[tuple[int, float], str]


def _site_model(
    *,
    address: str,
    apn: str,
    parcel_area_ft2: float,
    buildable_area_ft2: float,
    adu_width_ft: float,
    adu_depth_ft: float,
    fits_requested_size: bool,
    existing_footprint_ft2: float | None = 1500,
    front_edge_index: int | None = None,
) -> dict[str, Any]:
    buildings = (
        []
        if existing_footprint_ft2 is None
        else [{"area_ft2": existing_footprint_ft2}]
    )
    return {
        "address": address,
        "parcel": {"apn": apn, "area_ft2": parcel_area_ft2},
        "buildable_zone": {"area_ft2": buildable_area_ft2, "front_edge_index": front_edge_index},
        "adu": {
            "width_ft": adu_width_ft,
            "depth_ft": adu_depth_ft,
            "fits_requested_size": fits_requested_size,
        },
        "buildings": buildings,
    }


def _zoning(code: str) -> FetchResult[ZoningData]:
    return FetchResult.ok(
        ZoningData(
            zoning=code,
            zoning_abbrev=code,
            zoning_full_name=code,
            facility_id=None,
            rezoning_file=None,
            pd_use=None,
            pd_density=None,
            developed_as_pd=None,
            approval_date=None,
            notes=None,
        ),
        "test zoning",
    )


def _general_plan(designation: str) -> FetchResult[GeneralPlanData]:
    return FetchResult.ok(
        GeneralPlanData(
            gp_designation=designation,
            gp_abbreviation=designation[:8],
            notes=None,
            last_update=None,
        ),
        "test general plan",
    )


def _designation(present: bool, detail: str) -> FetchResult[DesignationData]:
    return FetchResult.ok(DesignationData(present=present, detail=detail), "test designation")


def _absent_designation() -> FetchResult[DesignationData]:
    return FetchResult.absent("test designation")


def _failed_designation() -> FetchResult[DesignationData]:
    return FetchResult.failed("service unavailable", "test designation")


def _clean_designations() -> dict[str, FetchResult[DesignationData]]:
    return {
        "flood": _absent_designation(),
        "geohazard": _absent_designation(),
        "historic": _absent_designation(),
        "wui": _absent_designation(),
        "heritage_trees": _absent_designation(),
    }


def _absent_permits() -> FetchResult[PermitsData]:
    return FetchResult.absent("test permits")


def _pool_permits() -> FetchResult[PermitsData]:
    pool = PermitRecord(
        folder_num="2024-POOL",
        work_desc="Swimming pool demolition",
        sub_desc="Remove existing pool",
        status="expired",
        issue_date="2024-01-10",
        final_date="2024-02-15",
    )
    return FetchResult.ok(
        PermitsData(
            active_count=0,
            finalized_count=1,
            records=[pool],
            has_pool_permit=True,
            pool_permits=[pool],
        ),
        "test permits",
    )


def _absent_code_enforcement() -> FetchResult[CodeEnforcementData]:
    return FetchResult.absent("test code enforcement")


def _active_code_enforcement() -> FetchResult[CodeEnforcementData]:
    issue = CodeIssue(
        issue_type="complaint",
        identifier="CE-1001",
        description="Unpermitted construction",
        open_date="2025-07-01",
        status="Open",
        program="Code Enforcement",
    )
    return FetchResult.ok(
        CodeEnforcementData(complaint_count=1, investigation_count=0, issues=[issue]),
        "test code enforcement",
    )


def _single_family_stats(sqft: float = 1800) -> dict[str, Any]:
    return {"found": True, "style": "Single Family", "sqft": sqft}


def _fixtures() -> list[ChecklistFixture]:
    clean_address = "1010 Alderbrook Lane, San Jose, CA"
    flagged_address = "200 E Santa Clara Street, San Jose, CA"
    unavailable_address = "1700 Alum Rock Avenue, San Jose, CA"

    return [
        ChecklistFixture(
            name="clean detached residential parcel",
            address=clean_address,
            site_model=_site_model(
                address=clean_address,
                apn="001-01-001",
                parcel_area_ft2=8500,
                buildable_area_ft2=2400,
                adu_width_ft=30,
                adu_depth_ft=30,
                fits_requested_size=True,
                existing_footprint_ft2=1600,
                front_edge_index=0,
            ),
            zoning=_zoning("R-1-8"),
            general_plan=_general_plan("Residential Neighborhood"),
            designations=_clean_designations(),
            property_stats=_single_family_stats(1900),
            adu_type="detached",
            permits=_absent_permits(),
            code_enforcement=_absent_code_enforcement(),
            expected_count=28,
            expected_statuses={
                (1, 3): "pass",
                (3, 10): "pass",
                (3, 11): "pass",
                (3, 13): "pass",
                (3, 14): "verify",
            },
        ),
        ChecklistFixture(
            name="flagged attached parcel with blockers",
            address=flagged_address,
            site_model=_site_model(
                address=flagged_address,
                apn="002-02-002",
                parcel_area_ft2=5200,
                buildable_area_ft2=350,
                adu_width_ft=35,
                adu_depth_ft=35,
                fits_requested_size=False,
                existing_footprint_ft2=2600,
            ),
            zoning=_zoning("CG"),
            general_plan=_general_plan("Combined Industrial/Commercial"),
            designations={
                "flood": _designation(True, "Zone: AE."),
                "geohazard": _designation(True, "In liquefaction zone."),
                "historic": _designation(True, "Historic area intersects this parcel."),
                "wui": _designation(True, "In Fire Wildland-Urban Interface."),
                "heritage_trees": _designation(True, "Heritage tree within parcel buffer."),
            },
            property_stats={"found": True, "style": "Commercial", "sqft": 1200},
            adu_type="attached",
            permits=_pool_permits(),
            code_enforcement=_active_code_enforcement(),
            expected_count=27,
            expected_statuses={
                (1, 3): "fail",
                (2, 4): "fail",
                (3, 10): "fail",
                (3, 11): "fail",
                (3, 13): "verify",
                (5, 22): "verify",
                (5, 23): "verify",
            },
        ),
        ChecklistFixture(
            name="jadu parcel with unavailable external data",
            address=unavailable_address,
            site_model=_site_model(
                address=unavailable_address,
                apn="003-03-003",
                parcel_area_ft2=7000,
                buildable_area_ft2=0,
                adu_width_ft=20,
                adu_depth_ft=25,
                fits_requested_size=True,
                existing_footprint_ft2=1400,
            ),
            zoning=FetchResult.failed("zoning timeout", "test zoning"),
            general_plan=FetchResult.failed("general plan timeout", "test general plan"),
            designations={
                "flood": _failed_designation(),
                "geohazard": _failed_designation(),
                "historic": _failed_designation(),
                "wui": _failed_designation(),
                "heritage_trees": _failed_designation(),
            },
            property_stats={},
            adu_type="jadu",
            permits=FetchResult.failed("permits timeout", "test permits"),
            code_enforcement=FetchResult.failed("code enforcement timeout", "test code enforcement"),
            expected_count=27,
            expected_statuses={
                (1, 3): "verify",
                (2, 4): "unavailable",
                (3, 10): "unavailable",
                (3, 11): "pass",
                (3, 13): "verify",
                (5, 22): "unavailable",
            },
        ),
    ]


def _build_for(fixture: ChecklistFixture) -> list[dict[str, Any]]:
    return build_checklist(
        fixture.site_model,
        zoning=fixture.zoning,
        general_plan=fixture.general_plan,
        designations=fixture.designations,
        property_stats=fixture.property_stats,
        adu_type=fixture.adu_type,
        permits=fixture.permits,
        code_enforcement=fixture.code_enforcement,
    )


def _by_part_and_number(items: list[dict[str, Any]]) -> dict[tuple[int, float], dict[str, Any]]:
    return {(int(item["part"]), float(item["number"])): item for item in items}


class SanJoseChecklistIntegrityTests(unittest.TestCase):
    def test_checklist_items_keep_expected_schema_and_order(self) -> None:
        for fixture in _fixtures():
            with self.subTest(fixture=fixture.name, address=fixture.address):
                items = _build_for(fixture)
                self.assertEqual(fixture.expected_count, len(items))

                seen: set[tuple[int, float]] = set()
                previous: tuple[int, float] | None = None
                parts = set()

                for item in items:
                    self.assertEqual(REQUIRED_KEYS, set(item))
                    self.assertIn(item["status"], VALID_STATUSES)
                    self.assertIsInstance(item["part"], int)
                    self.assertIsInstance(item["number"], (int, float))
                    self.assertIsInstance(item["question"], str)
                    self.assertIsInstance(item["detail"], str)
                    self.assertIsInstance(item["source"], str)
                    self.assertTrue(item["question"].strip())
                    self.assertTrue(item["detail"].strip())
                    self.assertTrue(item["source"].strip())

                    key = (item["part"], float(item["number"]))
                    self.assertNotIn(key, seen)
                    seen.add(key)
                    parts.add(item["part"])

                    if previous is not None:
                        self.assertGreaterEqual(key, previous)
                    previous = key

                self.assertEqual({1, 2, 3, 4, 5}, parts)

    def test_address_fixtures_cover_diverse_checklist_results(self) -> None:
        all_statuses: set[str] = set()

        for fixture in _fixtures():
            with self.subTest(fixture=fixture.name, address=fixture.address):
                items = _build_for(fixture)
                by_key = _by_part_and_number(items)
                all_statuses.update(item["status"] for item in items)

                self.assertEqual(fixture.address, fixture.site_model["address"])
                for key, expected_status in fixture.expected_statuses.items():
                    self.assertIn(key, by_key)
                    self.assertEqual(expected_status, by_key[key]["status"])

        self.assertTrue({"pass", "fail", "verify", "unavailable", "info"}.issubset(all_statuses))

    def test_detached_geometry_needs_selected_front_edge_for_setback_pass(self) -> None:
        address = "1010 Alderbrook Lane, San Jose, CA"
        site_model = _site_model(
            address=address,
            apn="001-01-001",
            parcel_area_ft2=8500,
            buildable_area_ft2=2400,
            adu_width_ft=30,
            adu_depth_ft=30,
            fits_requested_size=True,
            existing_footprint_ft2=1600,
            front_edge_index=None,
        )
        items = build_checklist(
            site_model,
            zoning=_zoning("R-1-8"),
            general_plan=_general_plan("Residential Neighborhood"),
            designations=_clean_designations(),
            property_stats=_single_family_stats(1900),
            adu_type="detached",
            permits=_absent_permits(),
            code_enforcement=_absent_code_enforcement(),
        )
        q13 = _by_part_and_number(items)[(3, 13)]

        self.assertEqual("verify", q13["status"])
        self.assertIn("Front property line was not selected", q13["detail"])

    def test_state_standard_geometry_needs_front_edge_for_front_setback(self) -> None:
        address = "1010 Alderbrook Lane, San Jose, CA"
        site_model = _site_model(
            address=address,
            apn="001-01-001",
            parcel_area_ft2=8500,
            buildable_area_ft2=2400,
            adu_width_ft=20,
            adu_depth_ft=30,
            fits_requested_size=True,
            existing_footprint_ft2=1600,
            front_edge_index=None,
        )
        items = build_checklist(
            site_model,
            zoning=_zoning("R-1-8"),
            general_plan=_general_plan("Residential Neighborhood"),
            designations=_clean_designations(),
            property_stats=_single_family_stats(1900),
            adu_type="detached",
            permits=_absent_permits(),
            code_enforcement=_absent_code_enforcement(),
            standards="state",
        )
        by_key = _by_part_and_number(items)

        self.assertEqual("verify", by_key[(3, 13)]["status"])
        self.assertEqual("verify", by_key[(3, 14.5)]["status"])
        self.assertIn("front setback/siting distance", by_key[(3, 13)]["detail"])

    def test_detached_geometry_needs_primary_outline_for_clearance_pass(self) -> None:
        address = "1010 Alderbrook Lane, San Jose, CA"
        site_model = _site_model(
            address=address,
            apn="001-01-001",
            parcel_area_ft2=8500,
            buildable_area_ft2=2400,
            adu_width_ft=30,
            adu_depth_ft=30,
            fits_requested_size=True,
            existing_footprint_ft2=None,
            front_edge_index=0,
        )
        items = build_checklist(
            site_model,
            zoning=_zoning("R-1-8"),
            general_plan=_general_plan("Residential Neighborhood"),
            designations=_clean_designations(),
            property_stats=_single_family_stats(1900),
            adu_type="detached",
            permits=_absent_permits(),
            code_enforcement=_absent_code_enforcement(),
        )
        by_key = _by_part_and_number(items)

        self.assertEqual("verify", by_key[(3, 13)]["status"])
        self.assertIn("No primary-residence footprint was found", by_key[(3, 13)]["detail"])
        self.assertEqual("verify", by_key[(3, 14.5)]["status"])

    def test_jadu_owner_occupancy_copy_is_conditional_on_sanitation(self) -> None:
        fixture = _fixtures()[2]
        items = _build_for(fixture)
        q24 = _by_part_and_number(items)[(5, 24)]

        self.assertIn("shared sanitation", q24["detail"])
        self.assertIn("independent sanitation", q24["detail"])


if __name__ == "__main__":
    unittest.main()
