import unittest

import numpy as np
import pandas as pd

from model import InfeasibleModelError, add_technology, example_inputs, solve
from stochastic import solve_stochastic


class CapacityLimitTests(unittest.TestCase):
    def test_zero_unlimited_with_existing_capacity_in_lp_and_integer(self):
        tech, _ = example_inputs()
        self.assertTrue((tech['Batas kapasitas (MW)'] == 0).all())
        tech = tech.iloc[[1]].copy()
        tech['Kapasitas tahun dasar (MW)'] = 35.
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [410.], 'PLTG': [1.]})
        for mode in ['continuous', 'integer']:
            r = solve(tech, profile, capacity_model=mode)
            self.assertAlmostEqual(r.summary['Kapasitas (MW)'].iloc[0], 410.)
            self.assertAlmostEqual(r.summary['Kapasitas baru (MW)'].iloc[0], 375.)
        tech['Batas kapasitas (MW)'] = 400.
        with self.assertRaises(InfeasibleModelError):
            solve(tech, profile)

    def test_unlimited_technology_can_be_added_with_existing_capacity(self):
        tech, profile = example_inputs()
        added, p = add_technology(tech, profile, 'PLTP', 100., 10., 5., 0., 0., 20., 10., 1., existing_mw=50.)
        self.assertEqual(added.iloc[-1]['Kapasitas tahun dasar (MW)'], 50.)
        solve(added, p, capacity_model='integer')

    def test_unlimited_diagnosis_handles_zero_availability_without_nan(self):
        tech, _ = example_inputs()
        tech = tech.iloc[:2].copy()
        tech['Batas kapasitas (MW)'] = [0., 5.]
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [10., 10.], 'PLTU': [1., 0.], 'PLTG': [1., 1.]})
        for mode in ['continuous', 'integer']:
            with self.assertRaises(InfeasibleModelError) as exc:
                solve(tech, profile, capacity_model=mode)
            d = exc.exception.diagnosis
            self.assertFalse(d['hourly']['Batas pembangkit (MW)'].isna().any())
            self.assertTrue(np.isinf(d['hourly']['Batas pembangkit (MW)'].iloc[0]))
            self.assertAlmostEqual(d['unserved_mwh_per_day'], 5. if mode == 'continuous' else 10.)
            self.assertFalse(any('PLTU' in s['Parameter'] for s in d['suggestions']))

    def test_stochastic_can_build_above_old_default_bound(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [400.], 'PLTG': [1.]})
        cases = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.5, .5], 'Faktor beban': [1., 1.5]})
        r = solve_stochastic(tech, profile, cases, capacity_model='integer')
        self.assertAlmostEqual(r.summary['Kapasitas (MW)'].iloc[0], 600.)


if __name__ == '__main__':
    unittest.main()
