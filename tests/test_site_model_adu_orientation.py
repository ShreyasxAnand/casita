from __future__ import annotations

import sys
import unittest
from pathlib import Path

from shapely.affinity import rotate
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.site_model import _candidate_angles, _dominant_angle, _front_depth_axis_angle


def _parallel_delta(a: float, b: float) -> float:
    return abs(((a - b + 90) % 180) - 90)


class SiteModelAduOrientationTests(unittest.TestCase):
    def test_dominant_angle_uses_long_property_axis(self) -> None:
        parcel = rotate(box(-30, -10, 30, 10), 30, origin=(0, 0), use_radians=False)

        self.assertLess(_parallel_delta(_dominant_angle(parcel), 30), 1e-6)

    def test_deep_adu_rotation_aligns_depth_axis_to_property_axis(self) -> None:
        rotations = _candidate_angles(30, width_m=6, depth_m=12)

        self.assertLess(_parallel_delta(rotations[0] + 90, 30), 1e-6)

    def test_wide_adu_rotation_aligns_width_axis_to_property_axis(self) -> None:
        rotations = _candidate_angles(30, width_m=12, depth_m=6)

        self.assertLess(_parallel_delta(rotations[0], 30), 1e-6)

    def test_selected_front_edge_uses_inward_front_to_back_axis(self) -> None:
        parcel = box(-30, -10, 30, 10)
        coords = list(parcel.exterior.coords)
        front_idx = min(
            range(len(coords) - 1),
            key=lambda i: (coords[i][1] + coords[i + 1][1]) / 2,
        )

        self.assertLess(_parallel_delta(_front_depth_axis_angle(parcel, front_idx), 90), 1e-6)


if __name__ == "__main__":
    unittest.main()
