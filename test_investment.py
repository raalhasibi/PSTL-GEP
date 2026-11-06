import unittest

import numpy as np
import pandas as pd

from model import BatteryConfig, InfeasibleModelError, add_technology, capital_recovery_factor, example_inputs, solve


class InvestmentTests(unittest.TestCase):
    def test_crf_zero_rate_and_known_annuity(self):
        self.assertAlmostEqual(float(capital_recovery_factor(0., 20.)), .05)
        self.assertAlmostEqual(float(capital_recovery_factor(.08, 25.)), .0936787790519681)

    def test_investment_changes_technology_choice_in_lp_and_integer(self):
        tech, profile = example_inputs()
        tech = tech.iloc[:2].copy()
        tech['Teknologi'] = ['A', 'B']
        tech['Investasi (USD/kW)'] = [1000., 100.]
        tech['O&M tetap (USD/kW/tahun)'] = 0.
        tech['Biaya variabel (USD/MWh)'] = [0., 50.]
        tech['Umur aset (tahun)'] = 10.
        tech['Ukuran blok (MW)'] = 5.
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [10., 10.], 'A': [1., 1.], 'B': [1., 1.]})
        for mode in ['continuous', 'integer']:
            with self.subTest(mode=mode):
                tech.loc[tech.Teknologi == 'B', 'Investasi (USD/kW)'] = 100.
                r = solve(tech, profile, days=1, capacity_model=mode, discount_rate=0.)
                np.testing.assert_allclose(r.summary['Kapasitas (MW)'], [0., 10.], atol=1e-7)
                self.assertAlmostEqual(r.annual_cost, 101000.)
                self.assertAlmostEqual(r.summary['Investasi awal (USD)'].sum(), 1000000.)
                tech.loc[tech.Teknologi == 'B', 'Investasi (USD/kW)'] = 2000.
                r = solve(tech, profile, days=1, capacity_model=mode, discount_rate=0.)
                np.testing.assert_allclose(r.summary['Kapasitas (MW)'], [10., 0.], atol=1e-7)

    def test_lifetime_and_discount_affect_annual_not_upfront_investment(self):
        tech, profile = example_inputs()
        tech = tech.iloc[[1]].copy()
        a = solve(tech, profile, discount_rate=0.)
        b = solve(tech, profile, discount_rate=.08)
        self.assertAlmostEqual(a.summary['Investasi awal (USD)'].sum(), b.summary['Investasi awal (USD)'].sum())
        self.assertGreater(b.annual_cost, a.annual_cost)
        tech['Umur aset (tahun)'] *= 2
        c = solve(tech, profile, discount_rate=0.)
        self.assertAlmostEqual(c.summary['Investasi tahunan (USD/tahun)'].sum(), a.summary['Investasi tahunan (USD/tahun)'].sum()/2)

    def test_new_technology_profile_and_integer_blocks(self):
        tech, profile = example_inputs()
        profile[tech.Teknologi] = 0.
        added, p = add_technology(tech, profile, '  PLTP  ', 1200., 25., 5., .05, 300., 30., 10., .9)
        self.assertNotIn('PLTP', profile.columns)
        self.assertEqual(len(tech), 4)
        self.assertEqual(len(added), 5)
        np.testing.assert_allclose(p.PLTP, .9)
        for mode, expected in [('continuous', 100/.9), ('integer', 120.)]:
            r = solve(added, p, capacity_model=mode)
            self.assertAlmostEqual(r.summary.loc[r.summary.Teknologi == 'PLTP', 'Kapasitas (MW)'].iloc[0], expected)
        added.loc[added.Teknologi == 'PLTP', 'Batas kapasitas (MW)'] = 100.
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(added, p, capacity_model='integer')
        self.assertTrue(any('PLTP' in s['Parameter'] for s in exc.exception.diagnosis['suggestions']))

    def test_new_technology_names_and_parameters_validated_atomically(self):
        tech, profile = example_inputs()
        for name in ['', '   ', 'pltu', ' PLTU ', 'Baterai', 'Jam', 'Beban (MW)']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                add_technology(tech, profile, name, 100., 10., 0., 0., 100., 20., 10., 1.)
        for lifetime, availability in [(0., .9), (20., 1.1)]:
            with self.assertRaises(ValueError):
                add_technology(tech, profile, 'PLTP', 100., 10., 0., 0., 100., lifetime, 10., availability)
        self.assertEqual(len(tech), 4)
        self.assertNotIn('PLTP', profile)

    def test_battery_capex_annualization_and_no_double_counting(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 10.], 'PLTS': [1., 0.]})
        battery = BatteryConfig(round_trip_efficiency=1., lifetime=10.)
        r = solve(tech, profile, capacity_model='integer', battery=battery, discount_rate=0.)
        b = r.battery_summary.iloc[0]
        upfront = 1000*(b['Daya (MW)']*300+b['Energi (MWh)']*150)
        self.assertAlmostEqual(b['Investasi awal (USD)'], upfront)
        self.assertAlmostEqual(b['Investasi tahunan (USD/tahun)'], upfront/10)
        self.assertAlmostEqual(b['Biaya tetap (USD/tahun)'], upfront/10+b['O&M tetap (USD/tahun)'])
        gen_cost = r.summary[['Biaya tetap (USD/tahun)', 'Biaya operasi (USD/tahun)', 'Biaya karbon (USD/tahun)']].to_numpy().sum()
        self.assertAlmostEqual(r.annual_cost, gen_cost+b['Biaya tetap (USD/tahun)']+b['Biaya operasi (USD/tahun)'])

    def test_invalid_lifetime_discount_and_missing_profiles(self):
        tech, profile = example_inputs()
        for rate in [-.1, float('nan')]:
            with self.assertRaises(ValueError):
                solve(tech, profile, discount_rate=rate)
        tech['Umur aset (tahun)'] = 0.
        with self.assertRaises(ValueError):
            solve(tech, profile)
        tech, profile = example_inputs()
        with self.assertRaisesRegex(ValueError, 'Profil per jam'):
            solve(tech, profile.drop(columns='PLTU'))


if __name__ == '__main__':
    unittest.main()
