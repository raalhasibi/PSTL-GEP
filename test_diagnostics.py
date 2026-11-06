import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
import pandas as pd

from model import BatteryConfig, InfeasibleModelError, example_inputs, solve


class DiagnosticTests(unittest.TestCase):
    def diagnose(self, tech, profile, **kwargs):
        with self.assertRaises(InfeasibleModelError) as caught:
            solve(tech, profile, **kwargs)
        return caught.exception.diagnosis

    def test_hourly_capacity_shortage_and_verified_repair(self):
        tech, profile = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Batas kapasitas (MW)'] = 80.
        report = self.diagnose(tech, profile)
        self.assertAlmostEqual(report['unserved_mwh_per_day'], np.maximum(profile['Beban (MW)']-80., 0.).sum())
        self.assertAlmostEqual(report['hourly']['Kekurangan pasti dari batas daya (MW)'].max(), 20.)
        suggestion = next(s for s in report['suggestions'] if 'Batas kapasitas' in s['Parameter'])
        tech['Batas kapasitas (MW)'] = suggestion['Contoh nilai layak']
        solve(tech, profile)

    def test_minimum_emissions_threshold_and_verified_repair(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [100., 100.], 'PLTG': [1., 1.]})
        report = self.diagnose(tech, profile, emissions_limit=10000.)
        self.assertAlmostEqual(report['minimum_emissions'], 200*.4*365)
        suggestion = next(s for s in report['suggestions'] if 'Batas emisi' in s['Parameter'])
        solve(tech, profile, emissions_limit=suggestion['Contoh nilai layak'])
        self.assertTrue(any('Mengubah biaya' in f for f in report['findings']))

    def test_integer_rounding_and_smaller_block_repair(self):
        tech, profile = example_inputs(101.)
        tech = tech.iloc[[1]].copy()
        tech['Batas kapasitas (MW)'] = 120.
        report = self.diagnose(tech, profile, capacity_model='integer')
        self.assertEqual(report['capacity']['Batas efektif (MW)'].iloc[0], 100.)
        self.assertEqual(report['capacity']['Tidak terpakai karena blok (MW)'].iloc[0], 20.)
        suggestion = next(s for s in report['suggestions'] if 'Ukuran blok' in s['Parameter'])
        solve(tech, profile, capacity_model='integer', block_sizes={'PLTG': suggestion['Contoh nilai layak']})

    @staticmethod
    def solar_case():
        tech, _ = example_inputs()
        return tech.iloc[[2]].copy(), pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 10.], 'PLTS': [1., 0.]})

    def test_battery_power_repair(self):
        tech, profile = self.solar_case()
        battery = BatteryConfig(max_power_mw=10., round_trip_efficiency=.81)
        report = self.diagnose(tech, profile, capacity_model='integer', battery=battery)
        suggestion = next(s for s in report['suggestions'] if s['Parameter'] == 'Batas daya baterai (MW)')
        battery.max_power_mw = suggestion['Contoh nilai layak']
        solve(tech, profile, capacity_model='integer', battery=battery)

    def test_battery_duration_repair(self):
        tech, profile = self.solar_case()
        battery = BatteryConfig(max_power_mw=20., duration_hours=.5, round_trip_efficiency=.81)
        report = self.diagnose(tech, profile, capacity_model='integer', battery=battery)
        suggestion = next(s for s in report['suggestions'] if s['Parameter'] == 'Durasi baterai (jam)')
        battery.duration_hours = suggestion['Contoh nilai layak']
        solve(tech, profile, capacity_model='integer', battery=battery)

    def test_no_generation_cannot_be_fixed_by_more_battery(self):
        tech, profile = self.solar_case()
        profile.PLTS = 0.
        report = self.diagnose(tech, profile, capacity_model='integer', battery=BatteryConfig())
        self.assertEqual(report['suggestions'], [])
        self.assertAlmostEqual(report['unserved_mwh_per_day'], 10.)
        self.assertTrue(any('tidak menghasilkan energi baru' in f for f in report['findings']))

    def test_combined_shortages_not_labeled_as_emissions_only(self):
        tech, profile = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Batas kapasitas (MW)'] = 80.
        report = self.diagnose(tech, profile, emissions_limit=1.)
        self.assertNotIn('minimum_emissions', report)
        self.assertEqual(report['suggestions'], [])
        self.assertTrue(any('Menghapus batas emisi saja' in f for f in report['findings']))

    def test_unfinished_diagnostic_is_not_reported_as_optimum(self):
        tech, profile = example_inputs()
        profile[tech.Teknologi] = 0.
        with patch('diagnostics.linprog', return_value=SimpleNamespace(success=False, status=1)):
            report = self.diagnose(tech, profile, emissions_limit=0.)
        self.assertNotIn('minimum_emissions', report)
        self.assertNotIn('unserved_mwh_per_day', report)
        self.assertEqual(report['suggestions'], [])
        self.assertTrue(any('belum selesai' in f for f in report['findings']))


if __name__ == '__main__':
    unittest.main()
