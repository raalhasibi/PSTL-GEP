import unittest

import numpy as np

from model import example_inputs, planning_profile


class PlanningTests(unittest.TestCase):
    def test_compound_growth_preserves_source_and_availability(self):
        _, profile = example_inputs()
        source = profile.copy()
        projected = planning_profile(profile, 2025, 5, .05)
        np.testing.assert_allclose(projected['Beban (MW)'], source['Beban (MW)']*1.05**5)
        self.assertTrue(profile.equals(source))
        self.assertTrue(projected.drop(columns='Beban (MW)').equals(source.drop(columns='Beban (MW)')))
        self.assertTrue(projected.equals(planning_profile(profile, 2025, 5, .05)))

    def test_zero_and_negative_growth(self):
        _, profile = example_inputs()
        self.assertTrue(planning_profile(profile, 2025, 10).equals(profile))
        self.assertAlmostEqual(planning_profile(profile, 2025, 2, -.1)['Beban (MW)'].max(), 81.)

    def test_invalid_years_growth_and_load(self):
        _, profile = example_inputs()
        for year, period, growth in [(2025.5, 1, 0.), (2025, 0, 0.), (2025, 51, 0.),
                                     (2025, 1.5, 0.), (2025, 1, -1.), (2025, 1, np.nan)]:
            with self.subTest(year=year, period=period, growth=growth), self.assertRaises(ValueError):
                planning_profile(profile, year, period, growth)
        profile['Beban (MW)'] = np.nan
        with self.assertRaises(ValueError):
            planning_profile(profile, 2025, 1)


if __name__ == '__main__':
    unittest.main()
