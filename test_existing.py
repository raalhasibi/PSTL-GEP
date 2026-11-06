"""Kapasitas lama, ekspansi residual, biaya sunk, dan kapasitas lintas skenario."""
import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from model import BatteryConfig, InfeasibleModelError, example_inputs, solve
from stochastic import solve_stochastic


class ExistingCapacityTests(unittest.TestCase):
    def inputs(self, demand=42., maximum=100.):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Kapasitas tahun dasar (MW)'] = 35.
        tech['Batas kapasitas (MW)'] = maximum
        tech['Ukuran blok (MW)'] = 10.
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [demand], 'PLTG': [1.]})
        return tech, profile

    def assert_costs(self, r):
        total = r.summary[['Biaya tetap (USD/tahun)', 'Biaya operasi (USD/tahun)', 'Biaya karbon (USD/tahun)']].to_numpy().sum()
        if r.storage_summary is not None:
            total += r.storage_summary[['Biaya tetap (USD/tahun)', 'Biaya operasi (USD/tahun)']].to_numpy().sum()
        self.assertAlmostEqual(r.annual_cost, total, places=5)

    def test_residual_expansion_continuous_and_integer(self):
        tech, profile = self.inputs()
        for mode, addition in [('continuous', 7.), ('integer', 10.)]:
            r = solve(tech, profile, capacity_model=mode, discount_rate=0.)
            row = r.summary.iloc[0]
            self.assertAlmostEqual(row['Kapasitas baru (MW)'], addition)
            self.assertAlmostEqual(row['Kapasitas (MW)'], 35.+addition)
            self.assertAlmostEqual(row['Investasi awal (USD)'], addition*700.*1000.)
            self.assertAlmostEqual(row['O&M tetap (USD/tahun)'], (35.+addition)*20.*1000.)
            self.assert_costs(r)

    def test_existing_only_has_no_investment_and_is_not_retired(self):
        tech, profile = self.inputs(demand=10., maximum=35.)
        for mode in ['continuous', 'integer']:
            r = solve(tech, profile, capacity_model=mode)
            self.assertEqual(r.summary['Kapasitas (MW)'].iloc[0], 35.)
            self.assertEqual(r.summary['Investasi awal (USD)'].sum(), 0.)
            self.assert_costs(r)

    def test_total_bound_diagnosis_and_verified_repair(self):
        tech, profile = self.inputs(maximum=44.)
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(tech, profile, capacity_model='integer')
        d = exc.exception.diagnosis
        self.assertEqual(d['capacity']['Batas efektif (MW)'].iloc[0], 35.)
        self.assertAlmostEqual(d['unserved_mwh_per_day'], 7.)
        suggestion = next(s for s in d['suggestions'] if s['Parameter'] == 'Batas kapasitas (MW) · PLTG')
        self.assertEqual(suggestion['Contoh nilai layak'], 45.)
        tech['Batas kapasitas (MW)'] = 45.
        solve(tech, profile, capacity_model='integer')

    def test_invalid_existing_capacity(self):
        tech, profile = self.inputs()
        for value in [-1., np.nan, 101.]:
            tech['Kapasitas tahun dasar (MW)'] = value
            with self.assertRaisesRegex(ValueError, 'tahun dasar'):
                solve(tech, profile)
        with self.assertRaises(ValueError):
            BatteryConfig(existing_power_mw=201.).validate()

    def test_storage_existing_non_multiple_and_new_blocks(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        tech['Kapasitas tahun dasar (MW)'] = 50.
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 12.], 'PLTS': [1., 0.]})
        storage = BatteryConfig(existing_power_mw=7., block_mw=10., max_power_mw=17.,
                                duration_hours=1., round_trip_efficiency=1.)
        r = solve(tech, profile, capacity_model='integer', storages={'Flow': storage})
        row = r.storage_summary.iloc[0]
        self.assertEqual(row['Daya (MW)'], 17.)
        self.assertEqual(row['Daya baru (MW)'], 10.)
        self.assertEqual(row['Jumlah blok'], 1)
        self.assertEqual(row['Investasi awal (USD)'], 10.*1000.*450.)
        self.assert_costs(r)
        profile['Beban (MW)'] = [0., 5.]
        r = solve(tech, profile, capacity_model='integer', battery=replace(storage, max_power_mw=7.))
        self.assertEqual(r.storage_summary['Investasi awal (USD)'].sum(), 0.)
        self.assertEqual(r.storage_summary['Daya (MW)'].iloc[0], 7.)
        self.assert_costs(r)

    def test_stochastic_shared_new_capacity_and_weighted_existing_om(self):
        tech, profile = self.inputs()
        scenarios = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.25, .75],
                                  'Faktor beban': [.5, 1.],
                                  'Pembangkit PLTG · O&M tetap (USD/kW/tahun)': [10., 50.]})
        r = solve_stochastic(tech, profile, scenarios, capacity_model='integer')
        for case in r.scenario_results.values():
            self.assertEqual(case.summary['Kapasitas baru (MW)'].iloc[0], 10.)
            self.assert_costs(case)
        self.assertAlmostEqual(r.annual_cost, .25*r.scenario_results['A'].annual_cost+.75*r.scenario_results['B'].annual_cost)
        self.assert_costs(r)

    def test_existing_storage_diagnosis_duration_repair(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 10.], 'PLTS': [1., 0.]})
        battery = BatteryConfig(existing_power_mw=12., max_power_mw=12., duration_hours=.5, round_trip_efficiency=1.)
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(tech, profile, capacity_model='integer', battery=battery)
        report = exc.exception.diagnosis
        self.assertEqual(report['hourly']['Batas daya baterai (MW)'].iloc[0], 12.)
        s = next(s for s in report['suggestions'] if s['Parameter'] == 'Durasi baterai (jam)')
        solve(tech, profile, capacity_model='integer', battery=replace(battery, duration_hours=s['Contoh nilai layak']))

    def test_stochastic_existing_storage_cost_is_included(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        tech['Kapasitas tahun dasar (MW)'] = 50.
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 5.], 'PLTS': [1., 0.]})
        battery = BatteryConfig(existing_power_mw=7., max_power_mw=7., duration_hours=1., round_trip_efficiency=1.)
        scenarios = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.4, .6],
                                  'Penyimpanan Baterai · O&M daya (USD/kW/tahun)': [10., 100.]})
        r = solve_stochastic(tech, profile, scenarios, capacity_model='integer', battery=battery)
        self.assertEqual(r.storage_summary['Investasi awal (USD)'].sum(), 0.)
        self.assertAlmostEqual(r.storage_summary['O&M tetap (USD/tahun)'].sum(), 7.*1000.*(.4*10.+.6*100.+2.))
        self.assert_costs(r)


if __name__ == '__main__':
    unittest.main()
