import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from model import BatteryConfig, InfeasibleModelError, example_inputs, solve
from stochastic import solve_stochastic
from storage_inputs import add_storage, empty_storage_table, storage_configs


class StorageTests(unittest.TestCase):
    @staticmethod
    def inputs():
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 30.], 'PLTS': [1., 0.]})
        a = BatteryConfig(block_mw=10., max_power_mw=10., duration_hours=1., round_trip_efficiency=1.)
        b = replace(a, max_power_mw=20.)
        return tech, profile, {'Lithium': a, 'Flow': b}

    def assert_physics(self, result):
        total_in, total_out = 0., 0.
        capacities = result.storage_summary.set_index('Teknologi')
        for name, operation in result.storage_dispatch.items():
            row = capacities.loc[name]
            eta = np.sqrt(row['Efisiensi round-trip (0–1)'])
            charge, discharge = operation['Isi baterai (MW)'], operation['Keluar baterai (MW)']
            np.testing.assert_allclose(operation['Energi akhir jam (MWh)'], operation['Energi awal jam (MWh)']+eta*charge-discharge/eta, atol=1e-6)
            self.assertAlmostEqual(operation['Energi awal jam (MWh)'].iloc[0], operation['Energi akhir jam (MWh)'].iloc[-1])
            self.assertTrue((charge <= row['Daya (MW)']+1e-6).all())
            self.assertTrue((discharge <= row['Daya (MW)']+1e-6).all())
            self.assertTrue((operation['Energi akhir jam (MWh)'] <= row['Energi (MWh)']+1e-6).all())
            self.assertTrue((charge*discharge < 1e-6).all())
            total_in = total_in+charge.to_numpy()
            total_out = total_out+discharge.to_numpy()
        np.testing.assert_allclose(result.dispatch['Isi baterai (MW)'], total_in, atol=1e-6)
        np.testing.assert_allclose(result.dispatch['Keluar baterai (MW)'], total_out, atol=1e-6)
        np.testing.assert_allclose(result.dispatch.PLTS+total_out-total_in, result.dispatch['Beban (MW)'], atol=1e-6)

    def test_two_storages_needed_and_separate_energy_balances(self):
        tech, profile, configs = self.inputs()
        result = solve(tech, profile, capacity_model='integer', storages=configs)
        self.assertEqual(result.storage_summary.Teknologi.tolist(), ['Lithium', 'Flow'])
        np.testing.assert_allclose(result.storage_summary['Jumlah blok'], [1, 2])
        self.assert_physics(result)
        costs = ['Biaya tetap (USD/tahun)', 'Biaya operasi (USD/tahun)']
        total = result.summary[costs+['Biaya karbon (USD/tahun)']].to_numpy().sum()+result.storage_summary[costs].to_numpy().sum()
        self.assertAlmostEqual(result.annual_cost, total)
        self.assertIn('Flow · Energi akhir (MWh)', result.dispatch)

    def test_optimizer_compares_storage_costs(self):
        tech, profile, configs = self.inputs()
        profile['Beban (MW)'] = [0., 10.]
        cheap = replace(configs['Lithium'], max_power_mw=100., investment_power=0., investment_energy=0., power_cost=1., energy_cost=0.)
        expensive = replace(cheap, power_cost=100.)
        result = solve(tech, profile, capacity_model='integer', storages={'Murah': cheap, 'Mahal': expensive})
        np.testing.assert_allclose(result.storage_summary['Jumlah blok'], [1, 0])
        self.assert_physics(result)

    def test_diagnosis_second_storage_power_bound_and_verified_repair(self):
        tech, profile, configs = self.inputs()
        configs['Flow'] = replace(configs['Flow'], max_power_mw=15.)
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(tech, profile, capacity_model='integer', storages=configs)
        report = exc.exception.diagnosis
        self.assertAlmostEqual(report['hourly']['Batas daya baterai (MW)'].iloc[0], 20.)
        suggestion = next(s for s in report['suggestions'] if s['Parameter'] == 'Batas daya (MW) · Flow')
        configs['Flow'] = replace(configs['Flow'], max_power_mw=suggestion['Contoh nilai layak'])
        solve(tech, profile, capacity_model='integer', storages=configs)

    def test_diagnosis_second_storage_duration_and_verified_repair(self):
        tech, profile, configs = self.inputs()
        profile['Beban (MW)'] = [0., 10.]
        configs = {'Disabled': replace(configs['Lithium'], max_power_mw=0.),
                   'Flow': replace(configs['Flow'], duration_hours=.5, round_trip_efficiency=.81)}
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(tech, profile, capacity_model='integer', storages=configs)
        suggestion = next(s for s in exc.exception.diagnosis['suggestions'] if s['Parameter'] == 'Durasi (jam) · Flow')
        configs['Flow'] = replace(configs['Flow'], duration_hours=suggestion['Contoh nilai layak'])
        result = solve(tech, profile, capacity_model='integer', storages=configs)
        self.assert_physics(result)

    def test_stochastic_shared_capacity_for_each_storage(self):
        tech, profile, configs = self.inputs()
        scenarios = pd.DataFrame({'Skenario': ['Low', 'High'], 'Probabilitas': [.5, .5], 'Faktor beban': [.5, 1.], 'Faktor PLTS': [1., 1.]})
        result = solve_stochastic(tech, profile, scenarios, capacity_model='integer', storages=configs)
        for case in result.scenario_results.values():
            np.testing.assert_allclose(case.storage_summary['Jumlah blok'], [1, 2])
            self.assert_physics(case)
        self.assertEqual(list(result.storage_dispatch), ['Lithium', 'Flow'])

    def test_registry_and_validation(self):
        tech, profile, configs = self.inputs()
        table = add_storage(empty_storage_table(), ' Flow ', configs['Flow'], tech.Teknologi)
        self.assertEqual(list(storage_configs(table)), ['Flow'])
        for name in ['', 'flow', 'PLTS', 'Baterai', 'Jam']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                add_storage(table, name, configs['Flow'], tech.Teknologi)
        for mapping in [{'PLTS': configs['Flow']}, {'Flow': configs['Flow'], 'flow': configs['Flow']}, {'Jam': configs['Flow']}]:
            with self.assertRaises(ValueError):
                solve(tech, profile, capacity_model='integer', storages=mapping)
        with self.assertRaises(ValueError):
            solve(tech, profile, storages=configs)


if __name__ == '__main__':
    unittest.main()
