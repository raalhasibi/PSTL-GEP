import unittest
import numpy as np
import pandas as pd
from model import BatteryConfig, example_inputs, solve


class ModelTests(unittest.TestCase):
    def test_balance_capacity_and_cost(self):
        tech, profile = example_inputs()
        r = solve(tech, profile)
        p = r.dispatch[tech.Teknologi].to_numpy()
        np.testing.assert_allclose(p.sum(axis=1), profile['Beban (MW)'], atol=1e-7)
        self.assertTrue((p <= profile[tech.Teknologi].to_numpy()*r.summary['Kapasitas (MW)'].to_numpy()+1e-7).all())
        self.assertAlmostEqual(r.annual_cost, r.summary.iloc[:, 3:6].to_numpy().sum())
        self.assertAlmostEqual(r.annual_energy, profile['Beban (MW)'].sum()*365)

    def test_single_generator_analytical_solution(self):
        tech, profile = example_inputs()
        tech = tech.iloc[[1]].copy()
        r = solve(tech, profile)
        self.assertAlmostEqual(r.summary['Kapasitas (MW)'].iloc[0], 100)
        annual_fixed = 20+700*.08/(1-1.08**-25)
        self.assertAlmostEqual(r.annual_cost, 100*annual_fixed*1000 + profile['Beban (MW)'].sum()*365*85)

    def test_emissions_constraint(self):
        tech, profile = example_inputs()
        baseline = solve(tech, profile)
        limit = baseline.annual_emissions*.8
        constrained = solve(tech, profile, emissions_limit=limit)
        self.assertLessEqual(constrained.annual_emissions, limit+1e-6)
        self.assertGreaterEqual(constrained.annual_cost+1e-6, baseline.annual_cost)

    def test_infeasible_and_invalid(self):
        tech, profile = example_inputs()
        tech.iloc[:, 4] = 0.
        with self.assertRaisesRegex(ValueError, 'Tidak ada solusi'):
            solve(tech, profile)
        tech, profile = example_inputs()
        profile.loc[0, 'PLTS'] = 1.5
        with self.assertRaisesRegex(ValueError, 'antara 0 dan 1'):
            solve(tech, profile)

    def test_integer_analytical_blocks_and_cost(self):
        tech, profile = example_inputs(101.)
        tech = tech.iloc[[1]].copy()
        r = solve(tech, profile, capacity_model='integer', block_sizes={'PLTG': 25.})
        self.assertEqual(r.summary['Jumlah blok'].iloc[0], 5)
        self.assertAlmostEqual(r.summary['Kapasitas (MW)'].iloc[0], 125.)
        annual_fixed = 20+700*.08/(1-1.08**-25)
        self.assertAlmostEqual(r.annual_cost, 125*annual_fixed*1000 + profile['Beban (MW)'].sum()*365*85)
        np.testing.assert_allclose(r.dispatch.PLTG, profile['Beban (MW)'])

    def test_integer_capacity_limit_is_not_rounded_up(self):
        tech, profile = example_inputs(101.)
        tech = tech.iloc[[1]].copy()
        tech['Batas kapasitas (MW)'] = 120.
        self.assertAlmostEqual(solve(tech, profile).summary['Kapasitas (MW)'].iloc[0], 101.)
        with self.assertRaisesRegex(ValueError, 'Tidak ada solusi'):
            solve(tech, profile, capacity_model='integer', block_sizes={'PLTG': 25.})

    def test_integer_balance_emissions_and_lp_lower_bound(self):
        tech, profile = example_inputs()
        lp = solve(tech, profile, carbon_price=50., emissions_limit=150000.)
        r = solve(tech, profile, carbon_price=50., emissions_limit=150000., capacity_model='integer')
        self.assertGreaterEqual(r.annual_cost+1e-5, lp.annual_cost)
        self.assertLessEqual(r.annual_emissions, 150000.+1e-5)
        np.testing.assert_allclose(r.summary['Kapasitas (MW)'],
                                   r.summary['Jumlah blok']*r.summary['Ukuran blok (MW)'], atol=1e-7)
        p = r.dispatch[tech.Teknologi].to_numpy()
        np.testing.assert_allclose(p.sum(axis=1), profile['Beban (MW)'], atol=1e-7)
        self.assertTrue((p <= profile[tech.Teknologi].to_numpy()*r.summary['Kapasitas (MW)'].to_numpy()+1e-7).all())
        self.assertTrue((r.summary['Kapasitas (MW)'].to_numpy() <= tech['Batas kapasitas (MW)'].to_numpy()+1e-7).all())

    def test_invalid_blocks(self):
        tech, profile = example_inputs()
        for value in [0., -1., float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Ukuran blok'):
                solve(tech, profile, capacity_model='integer', block_sizes={n: value for n in tech.Teknologi})
        with self.assertRaisesRegex(ValueError, 'setiap teknologi'):
            solve(tech, profile, capacity_model='integer', block_sizes={})

    @staticmethod
    def solar_battery_case():
        tech, _ = example_inputs()
        tech = tech[tech.Teknologi == 'PLTS'].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [0., 10.], 'PLTS': [1., 0.]})
        return tech, profile

    def test_battery_analytical_solar_shift_and_losses(self):
        tech, profile = self.solar_battery_case()
        battery = BatteryConfig(duration_hours=2., round_trip_efficiency=.81)
        r = solve(tech, profile, capacity_model='integer', battery=battery)
        bs = r.battery_summary.iloc[0]
        self.assertEqual(bs['Jumlah blok'], 2)
        self.assertEqual(bs['Daya (MW)'], 20.)
        self.assertEqual(bs['Energi (MWh)'], 40.)
        self.assertAlmostEqual(r.summary['Kapasitas (MW)'].iloc[0], 20.)
        d = r.dispatch
        charge = d['Isi baterai (MW)'].to_numpy()
        discharge = d['Keluar baterai (MW)'].to_numpy()
        # Daya isi per blok perlu >= 10/.81 MW; blok 10 MW memerlukan 2 blok!
        self.assertAlmostEqual(charge.sum(), 10/.81)
        self.assertAlmostEqual(discharge.sum(), 10.)
        np.testing.assert_allclose(d.PLTS + discharge - charge, profile['Beban (MW)'], atol=1e-7)
        np.testing.assert_allclose(d['Energi akhir jam (MWh)'],
                                   d['Energi awal jam (MWh)']+.9*charge-discharge/.9, atol=1e-7)
        self.assertAlmostEqual(d['Energi awal jam (MWh)'].iloc[0], d['Energi akhir jam (MWh)'].iloc[-1])
        self.assertTrue((charge*discharge < 1e-7).all())
        self.assertTrue((charge <= bs['Daya (MW)']+1e-7).all())
        self.assertTrue((discharge <= bs['Daya (MW)']+1e-7).all())
        self.assertTrue((d['Energi akhir jam (MWh)'] <= bs['Energi (MWh)']+1e-7).all())
        self.assertAlmostEqual(bs['Rugi energi (MWh/tahun)'], (10/.81-10)*365)
        generator_cost = r.summary[['Biaya tetap (USD/tahun)', 'Biaya operasi (USD/tahun)', 'Biaya karbon (USD/tahun)']].to_numpy().sum()
        self.assertAlmostEqual(r.annual_cost, generator_cost+bs['Biaya tetap (USD/tahun)']+bs['Biaya operasi (USD/tahun)'])

    def test_battery_no_free_initial_energy_or_fractional_block(self):
        tech, profile = self.solar_battery_case()
        with self.assertRaisesRegex(ValueError, 'Tidak ada solusi'):
            solve(tech, profile, capacity_model='integer', battery=BatteryConfig(max_power_mw=9.))
        profile.PLTS = 0.
        with self.assertRaisesRegex(ValueError, 'Tidak ada solusi'):
            solve(tech, profile, capacity_model='integer', battery=BatteryConfig())

    def test_zero_battery_capacity_matches_existing_integer_model(self):
        tech, profile = example_inputs()
        baseline = solve(tech, profile, capacity_model='integer', emissions_limit=10000., carbon_price=50.)
        r = solve(tech, profile, capacity_model='integer', battery=BatteryConfig(max_power_mw=0.),
                  emissions_limit=10000., carbon_price=50.)
        self.assertAlmostEqual(r.annual_cost, baseline.annual_cost, places=3)
        self.assertEqual(r.battery_summary['Jumlah blok'].iloc[0], 0)
        self.assertLessEqual(r.annual_emissions, 10000.+1e-6)

    def test_invalid_battery_inputs(self):
        tech, profile = example_inputs()
        for setting in [{'block_mw': 0.}, {'duration_hours': -1.}, {'round_trip_efficiency': 0.},
                        {'round_trip_efficiency': 1.1}, {'power_cost': -1.}, {'energy_cost': float('nan')}]:
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                solve(tech, profile, capacity_model='integer', battery=BatteryConfig(**setting))
        with self.assertRaisesRegex(ValueError, 'model blok integer'):
            solve(tech, profile, battery=BatteryConfig())

    def test_battery_energy_capacity_can_drive_block_count(self):
        tech, profile = self.solar_battery_case()
        r = solve(tech, profile, capacity_model='integer',
                  battery=BatteryConfig(duration_hours=.5, round_trip_efficiency=.81))
        self.assertEqual(r.battery_summary['Jumlah blok'].iloc[0], 3)
        self.assertEqual(r.battery_summary['Energi (MWh)'].iloc[0], 15.)


if __name__ == '__main__':
    unittest.main()
