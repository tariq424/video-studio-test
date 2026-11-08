"""Synthetic physics profiles (physics.synthetic_profile): real laws of motion on the narration's numbers, never a fixed sine."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import physics


def prof(vo):
    return physics.synthetic_profile({"vo": vo})


class SyntheticProfiles(unittest.TestCase):
    def test_no_sine_path_left(self):
        for vo in ["A train travels 300 km from A to B.", "The convoy drove 40 miles toward the border.", "Ships moving on a route at 30 km/h"]:
            r = physics.synthetic_motion({"vo": vo})
            self.assertIsNotNone(r, vo)
            self.assertNotEqual(r.get("module"), "physical_flow")

    def test_crash_uses_narration_speed(self):
        r = prof("The car slammed into the barrier at 70 mph.")
        self.assertEqual(r["module"], "synthetic_brake")
        self.assertAlmostEqual(r["series"][0][1], 112.6, delta=0.5)   # 70 mph in km/h
        self.assertEqual(r["series"][-1][1], 0)
        self.assertIn("g)", r["label"])

    def test_free_fall_with_drag(self):
        r = prof("Debris fell 300 feet from the bridge.")
        self.assertEqual(r["module"], "synthetic_free_fall")
        self.assertAlmostEqual(r["series"][0][1], 91.4, delta=0.2)
        self.assertEqual(r["series"][-1][1], 0)
        t_end = r["series"][-1][0]
        self.assertGreater(t_end, (2 * 91.44 / 9.81) ** 0.5)   # drag makes it slower than a vacuum fall

    def test_travel_speed_from_distance_and_time(self):
        r = prof("The truck convoy drove 400 km in 5 hours.")
        self.assertEqual(r["module"], "synthetic_travel")
        self.assertAlmostEqual(r["series"][-1][1], 400, delta=3)   # km covered (speed 80 km/h worked out from 400 km / 5 h)
        self.assertIn("80 km/h", r["label"])
        self.assertNotIn("assumed", r["notes"])

    def test_storm_peak_from_narration(self):
        r = prof("Hurricane winds grew from 75 mph to 140 mph.")
        self.assertEqual(r["module"], "synthetic_storm_build")
        self.assertEqual(r["series"][0][1], 75)
        self.assertEqual(max(v for _, v in r["series"]), 140)

    def test_assumptions_are_shown(self):
        self.assertIsNone(prof("The rocket lifted off from Cape Canaveral."))   # no stated number: no chart
        r = prof("The rocket lifted off from Cape Canaveral and burned for 150 seconds.")   # one stated number: the rest assumed, shown
        self.assertEqual(r["module"], "synthetic_launch")
        self.assertTrue(r["synthetic"])
        self.assertIn("assumed", r["notes"])

    def test_figurative_motion_gets_nothing(self):
        for vo in ["The market moves higher.", "The new MacBook moves fast", "Shares fell 20% after the crash."]:
            self.assertIsNone(prof(vo), vo)


if __name__ == "__main__":
    unittest.main()
