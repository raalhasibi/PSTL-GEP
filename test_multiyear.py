import unittest

import numpy as np
import pandas as pd

from model import BatteryConfig, InfeasibleModelError, example_inputs, solve
from multiyear import build_multiyear_problem, solve_multiyear
from stochastic import solve_stochastic


class MultiYearTests(unittest.TestCase):
    def test_manual_forecast_and_stochastic_factor_are_both_applied(self):
        tech, profile = self.inputs()
        tech['Kapasitas tahun dasar (MW)'] = 0.
        scenarios = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.5, .5], 'Faktor beban': [1., 2.]})
        r = solve_stochastic(tech, profile, scenarios, problem_builder=build_multiyear_problem,
            base_year=2025, planning_years=2, annual_growth=.9, annual_load_factors={2026: 1.3, 2027: 1.6}, capacity_model='integer')
        self.assertAlmostEqual(r.scenario_results['B'].year_results[2026].dispatch['Beban (MW)'].max(), 26.)
        self.assertAlmostEqual(r.scenario_results['B'].year_results[2027].dispatch['Beban (MW)'].max(), 32.)
        np.testing.assert_allclose(r.capacity_plan['Kapasitas (MW)'], [30., 35.])
        for factors in [{2026: 1.}, {2026: 1., 2027: 0.}, {2026: 1., 2027: np.nan}]:
            with self.assertRaises(ValueError):
                solve_multiyear(tech, profile, planning_years=2, annual_load_factors=factors)

    def inputs(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Kapasitas tahun dasar (MW)'] = 10.
        tech['Ukuran blok (MW)'] = 5.
        return tech, pd.DataFrame({'Jam': [0], 'Beban (MW)': [10.], 'PLTG': [1.]})

    def test_continuous_annual_additions_and_discounted_cumulative_cost(self):
        tech, profile = self.inputs()
        r = solve_multiyear(tech, profile, base_year=2025, planning_years=3, annual_growth=.1, days=1)
        plan = r.capacity_plan
        np.testing.assert_allclose(plan['Kapasitas (MW)'], [11., 12.1, 13.31])
        np.testing.assert_allclose(plan['Kapasitas awal tahun (MW)'], [10., 11., 12.1])
        np.testing.assert_allclose(plan['Kapasitas baru (MW)'], [1., 1.1, 1.21])
        self.assertAlmostEqual(plan['Investasi awal (USD)'].sum(), 3.31*700.*1000.)
        costs = []
        for year, yr in r.year_results.items():
            row = yr.summary.iloc[0]
            expected = row['Investasi tahunan (USD/tahun)']+row['O&M tetap (USD/tahun)']+row['Biaya operasi (USD/tahun)']
            self.assertAlmostEqual(yr.annual_cost, expected)
            costs.append(expected/1.08**(year-2025))
            self.assertAlmostEqual(yr.dispatch.PLTG.iloc[0], yr.dispatch['Beban (MW)'].iloc[0])
        self.assertAlmostEqual(r.npv_cost, sum(costs))
        self.assertAlmostEqual(r.npv_cost, r.annual_metrics['Kontribusi biaya kini (USD)'].sum())
        self.assertEqual(profile['Beban (MW)'].iloc[0], 10.)

    def test_integer_build_once_and_keep_capacity_in_subsequent_years(self):
        tech, profile = self.inputs()
        r = solve_multiyear(tech, profile, planning_years=3, annual_growth=.1, capacity_model='integer')
        np.testing.assert_allclose(r.capacity_plan['Jumlah blok'], [1, 0, 0])
        np.testing.assert_allclose(r.capacity_plan['Kapasitas (MW)'], [15., 15., 15.])
        np.testing.assert_allclose(r.capacity_plan['Kapasitas baru (MW)'], [5., 0., 0.])
        self.assertEqual(r.capacity_plan['Investasi awal (USD)'].iloc[1], 0.)
        self.assertGreater(r.capacity_plan['Investasi tahunan (USD/tahun)'].iloc[1], 0.)

    def test_declining_load_does_not_retire_capacity(self):
        tech, profile = self.inputs()
        tech['Kapasitas tahun dasar (MW)'] = 0.
        r = solve_multiyear(tech, profile, planning_years=3, annual_growth=-.1)
        np.testing.assert_allclose(r.capacity_plan['Kapasitas (MW)'], [9., 9., 9.])
        np.testing.assert_allclose(r.capacity_plan['Kapasitas baru (MW)'], [9., 0., 0.])

    def test_one_year_matches_previous_model(self):
        tech, profile = self.inputs()
        a = solve(tech, profile)
        b = solve_multiyear(tech, profile)
        self.assertAlmostEqual(a.annual_cost, b.annual_cost)
        self.assertAlmostEqual(b.npv_cost, a.annual_cost/1.08)

    def test_storage_schedule_and_independent_cyclic_operation_each_year(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 5.], 'PLTS': [1., 0.]})
        b = BatteryConfig(existing_power_mw=3., block_mw=5., duration_hours=1., round_trip_efficiency=1.)
        r = solve_multiyear(tech, profile, planning_years=2, annual_growth=.2, capacity_model='integer', battery=b)
        np.testing.assert_allclose(r.storage_plan['Daya (MW)'], [8., 8.])
        np.testing.assert_allclose(r.storage_plan['Daya baru (MW)'], [5., 0.])
        np.testing.assert_allclose(r.storage_plan['Jumlah blok'], [1, 0])
        for year, yr in r.year_results.items():
            operation = yr.storage_dispatch['Baterai']
            self.assertAlmostEqual(operation['Energi awal jam (MWh)'].iloc[0], operation['Energi akhir jam (MWh)'].iloc[-1])
            np.testing.assert_allclose(yr.dispatch.PLTS+yr.dispatch['Keluar baterai (MW)']-yr.dispatch['Isi baterai (MW)'], yr.dispatch['Beban (MW)'])

    def test_failure_identifies_first_infeasible_year(self):
        tech, profile = self.inputs()
        tech['Batas kapasitas (MW)'] = 12.
        with self.assertRaises(InfeasibleModelError) as exc:
            solve_multiyear(tech, profile, base_year=2025, planning_years=3, annual_growth=.1)
        self.assertIn('2027', str(exc.exception))
        self.assertTrue(any('2027' in f for f in exc.exception.diagnosis['findings']))

    def test_stochastic_shared_schedule_and_expected_npv(self):
        tech, profile = self.inputs()
        tech['Kapasitas tahun dasar (MW)'] = 0.
        scenarios = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.25, .75], 'Faktor beban': [1., 2.]})
        r = solve_stochastic(tech, profile, scenarios, problem_builder=build_multiyear_problem,
            base_year=2025, planning_years=2, annual_growth=.1, capacity_model='integer')
        self.assertEqual(list(r.year_results), [2026, 2027])
        for case in r.scenario_results.values():
            np.testing.assert_allclose(case.capacity_plan['Kapasitas (MW)'], [25., 25.])
            np.testing.assert_allclose(case.capacity_plan['Kapasitas baru (MW)'], [25., 0.])
        self.assertAlmostEqual(r.npv_cost, .25*r.scenario_results['A'].npv_cost+.75*r.scenario_results['B'].npv_cost)
        for year, yr in r.year_results.items():
            self.assertAlmostEqual(yr.annual_cost, .25*r.scenario_results['A'].year_results[year].annual_cost+.75*r.scenario_results['B'].year_results[year].annual_cost)


if __name__ == '__main__':
    unittest.main()
