import unittest

import numpy as np
import pandas as pd

from model import BatteryConfig, example_inputs, solve
from stochastic import StochasticInfeasibleError, example_scenarios, resize_scenarios, solve_stochastic, uncertainty_catalog


class StochasticTests(unittest.TestCase):
    @staticmethod
    def scenarios(names, factors=(1., 2.), probabilities=(.75, .25)):
        table = pd.DataFrame({'Skenario': ['Rendah', 'Tinggi'], 'Probabilitas': probabilities, 'Faktor beban': factors})
        for name in names:
            table[f'Faktor {name}'] = 1.
        return table

    def test_one_scenario_matches_deterministic_all_modes(self):
        tech, profile = example_inputs()
        scenarios = example_scenarios(tech.Teknologi).iloc[[1]].copy()
        scenarios['Probabilitas'] = 1.
        for mode, battery in [('continuous', None), ('integer', None), ('integer', BatteryConfig())]:
            with self.subTest(mode=mode, battery=battery is not None):
                baseline = solve(tech, profile, capacity_model=mode, battery=battery)
                r = solve_stochastic(tech, profile, scenarios, capacity_model=mode, battery=battery)
                self.assertAlmostEqual(r.annual_cost, baseline.annual_cost, places=3)
                np.testing.assert_allclose(r.summary['Kapasitas (MW)'], baseline.summary['Kapasitas (MW)'], atol=1e-5)

    def test_shared_capacity_and_fixed_cost_only_once(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Investasi (USD/kW)'] = 0.
        tech['O&M tetap (USD/kW/tahun)'] = 10.
        tech['Biaya variabel (USD/MWh)'] = 3.
        tech['Ukuran blok (MW)'] = 5.
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [10., 10.], 'PLTG': [1., 1.]})
        scenarios = self.scenarios(tech.Teknologi)
        for mode in ['continuous', 'integer']:
            r = solve_stochastic(tech, profile, scenarios, capacity_model=mode)
            self.assertAlmostEqual(r.summary['Kapasitas (MW)'].iloc[0], 20.)
            self.assertAlmostEqual(r.annual_cost, 200000.+25*365*3)
            self.assertAlmostEqual(r.annual_energy, 25*365)
            for case in r.scenario_results.values():
                self.assertAlmostEqual(case.summary['Kapasitas (MW)'].iloc[0], 20.)
            self.assertAlmostEqual(r.annual_cost, r.scenario_metrics['Kontribusi biaya ekspektasian (USD/tahun)'].sum())

    def test_probability_changes_capacity_mix(self):
        tech, _ = example_inputs()
        tech = tech.iloc[:2].copy()
        tech['Teknologi'] = ['Dasar', 'Peaker']
        tech['Investasi (USD/kW)'] = 0.
        tech['O&M tetap (USD/kW/tahun)'] = [20., 1.]
        tech['Biaya variabel (USD/MWh)'] = [0., 100.]
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [1.], 'Dasar': [1.], 'Peaker': [1.]})
        a = solve_stochastic(tech, profile, self.scenarios(tech.Teknologi, (1., 10.), (.9, .1)))
        b = solve_stochastic(tech, profile, self.scenarios(tech.Teknologi, (1., 10.), (.1, .9)))
        np.testing.assert_allclose(a.summary['Kapasitas (MW)'], [1., 9.], atol=1e-6)
        np.testing.assert_allclose(b.summary['Kapasitas (MW)'], [10., 0.], atol=1e-6)

    def test_battery_shared_blocks_balance_and_cycle_per_scenario(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 10.], 'PLTS': [1., 0.]})
        battery = BatteryConfig(duration_hours=2., round_trip_efficiency=.81)
        r = solve_stochastic(tech, profile, self.scenarios(tech.Teknologi, probabilities=(.5, .5)),
                             capacity_model='integer', battery=battery)
        self.assertEqual(r.battery_summary['Jumlah blok'].iloc[0], 3)
        for case in r.scenario_results.values():
            self.assertEqual(case.battery_summary['Jumlah blok'].iloc[0], 3)
            d = case.dispatch
            np.testing.assert_allclose(d.PLTS+d['Keluar baterai (MW)']-d['Isi baterai (MW)'], d['Beban (MW)'], atol=1e-6)
            self.assertAlmostEqual(d['Energi awal jam (MWh)'].iloc[0], d['Energi akhir jam (MWh)'].iloc[-1])
            self.assertTrue((d['Isi baterai (MW)']*d['Keluar baterai (MW)'] < 1e-6).all())
        self.assertAlmostEqual(r.battery_summary['Rugi energi (MWh/tahun)'].iloc[0], (15/.81-15)*365)

    def test_infeasible_scenario_is_identified(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Batas kapasitas (MW)'] = 15.
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [10.], 'PLTG': [1.]})
        with self.assertRaises(StochasticInfeasibleError) as exc:
            solve_stochastic(tech, profile, self.scenarios(tech.Teknologi))
        self.assertEqual(list(exc.exception.scenario_diagnoses), ['Tinggi'])
        self.assertIn('hourly', exc.exception.scenario_diagnoses['Tinggi'])

    def test_emissions_cap_enforced_per_scenario(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Emisi (tCO2/MWh)'] = 1.
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [10.], 'PLTG': [1.]})
        with self.assertRaises(StochasticInfeasibleError) as exc:
            solve_stochastic(tech, profile, self.scenarios(tech.Teknologi), emissions_limit=15*365)
        self.assertEqual(list(exc.exception.scenario_diagnoses), ['Tinggi'])

    def test_probabilities_and_names_are_validated(self):
        tech, profile = example_inputs()
        for probabilities in [(0., 1.), (.1, .2), (-.1, 1.1), (float('nan'), 1.)]:
            with self.subTest(probabilities=probabilities), self.assertRaises(ValueError):
                solve_stochastic(tech, profile, self.scenarios(tech.Teknologi, probabilities=probabilities))
        scenarios = self.scenarios(tech.Teknologi)
        scenarios.Skenario = ['sama', 'SAMA']
        with self.assertRaises(ValueError):
            solve_stochastic(tech, profile, scenarios)

    def test_only_selected_parameters_are_used(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [10.], 'PLTG': [1.]})
        cases = self.scenarios(tech.Teknologi, (.8, 1.2), (.5, .5))
        cases['Faktor PLTG'] = 0.  # Akan infeasible jika parameter tersembunyi ikut diterapkan.
        r = solve_stochastic(tech, profile, cases, uncertainty_parameters=['Faktor beban'])
        self.assertAlmostEqual(r.summary['Kapasitas (MW)'].iloc[0], 12.)
        self.assertNotIn('Faktor PLTG', r.scenario_inputs)
        self.assertTrue((cases['Faktor PLTG'] == 0.).all())

    def test_absolute_variable_cost_values_and_carbon_prices(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Investasi (USD/kW)'] = 0.
        tech['O&M tetap (USD/kW/tahun)'] = 10.
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [10.], 'PLTG': [1.]})
        column = 'Pembangkit PLTG · Biaya variabel (USD/MWh)'
        cases = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.25, .75], column: [3., 9.], 'Harga karbon (USD/tCO2)': [0., 100.]})
        r = solve_stochastic(tech, profile, cases, uncertainty_parameters=[column, 'Harga karbon (USD/tCO2)'])
        expected = 100000.+10*365*(.25*3+.75*(9+100*.4))
        self.assertAlmostEqual(r.annual_cost, expected)
        self.assertEqual(tech['Biaya variabel (USD/MWh)'].iloc[0], 85.)

    def test_crf_and_investment_evaluated_per_scenario(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Investasi (USD/kW)'] = 1000.
        tech['Umur aset (tahun)'] = 10.
        tech['O&M tetap (USD/kW/tahun)'] = 0.
        tech['Biaya variabel (USD/MWh)'] = 0.
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [10.], 'PLTG': [1.]})
        capex = 'Pembangkit PLTG · Investasi (USD/kW)'
        cases = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.5, .5], 'Tingkat diskonto (%)': [0., 20.], capex: [1000., 2000.]})
        r = solve_stochastic(tech, profile, cases, uncertainty_parameters=['Tingkat diskonto (%)', capex])
        expected = 10*1000*(.5*1000/10+.5*2000*.2/(1-1.2**-10))
        self.assertAlmostEqual(r.annual_cost, expected)
        self.assertAlmostEqual(r.summary['Investasi awal (USD)'].iloc[0], 15000000.)
        for case in r.scenario_results.values():
            self.assertAlmostEqual(case.summary['Kapasitas (MW)'].iloc[0], 10.)

    def test_user_selected_storage_efficiency_and_invalid_values(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 10.], 'PLTS': [1., 0.]})
        config = BatteryConfig(duration_hours=2.)
        column = 'Penyimpanan Flow · Efisiensi round-trip (%)'
        cases = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.5, .5], column: [100., 81.]})
        r = solve_stochastic(tech, profile, cases, uncertainty_parameters=[column], capacity_model='integer', storages={'Flow': config})
        self.assertAlmostEqual(r.scenario_results['A'].storage_dispatch['Flow']['Isi baterai (MW)'].sum(), 10.)
        self.assertAlmostEqual(r.scenario_results['B'].storage_dispatch['Flow']['Isi baterai (MW)'].sum(), 10/.81)
        self.assertEqual(config.round_trip_efficiency, .9)
        for invalid in [0., 101.]:
            cases.loc[0, column] = invalid
            with self.assertRaises(ValueError):
                solve_stochastic(tech, profile, cases, uncertainty_parameters=[column], capacity_model='integer', storages={'Flow': config})

    def test_user_scenario_counts_two_three_and_more_than_eight(self):
        tech, profile = example_inputs()
        baseline = solve(tech, profile)
        for count in [2, 3, 10]:
            cases = pd.DataFrame({'Skenario': [f'S{i}' for i in range(count)], 'Probabilitas': [1/count]*count})
            r = solve_stochastic(tech, profile, cases, uncertainty_parameters=[])
            self.assertEqual(len(r.scenario_results), count)
            self.assertAlmostEqual(r.annual_cost, baseline.annual_cost, places=3)

    def test_resize_preserves_existing_values_and_initializes_parameters(self):
        tech, _ = example_inputs()
        catalog = uncertainty_catalog(tech)
        original = example_scenarios(tech.Teknologi)
        original.loc[0, 'Faktor beban'] = 1.37
        resized, changed = resize_scenarios(original, 5, catalog)
        self.assertTrue(changed)
        self.assertEqual(len(resized), 5)
        self.assertEqual(resized.loc[0, 'Faktor beban'], 1.37)
        np.testing.assert_allclose(resized.Probabilitas, .2)
        self.assertEqual(resized.loc[4, 'Faktor beban'], 1.)
        self.assertEqual(resized.loc[4, 'Harga karbon (USD/tCO2)'], 0.)
        two, _ = resize_scenarios(resized, 2, catalog)
        self.assertEqual(two.loc[0, 'Faktor beban'], 1.37)
        np.testing.assert_allclose(two.Probabilitas, .5)

    def test_physical_design_parameter_not_accepted_as_uncertain(self):
        tech, profile = example_inputs()
        cases = example_scenarios(tech.Teknologi)
        with self.assertRaisesRegex(ValueError, 'tidak dikenal'):
            solve_stochastic(tech, profile, cases, uncertainty_parameters=['Ukuran blok (MW)'])


if __name__ == '__main__':
    unittest.main()
