import unittest

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from exogenous import EXOGENOUS_COLUMNS, validate_exogenous
from model import InfeasibleModelError, example_inputs
from multiyear import build_multiyear_problem, solve_multiyear
from stochastic import solve_stochastic
from excel_inputs import default_template_frames, validate_excel_frames, read_excel_inputs, TEMPLATE_PATH


class ExogenousTests(unittest.TestCase):
    def inputs(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Ukuran blok (MW)'] = 5.
        profile = pd.DataFrame({'Jam': [0], 'Beban (MW)': [10.], 'PLTG': [1.]})
        return tech, profile

    def table(self, rows):
        return pd.DataFrame(rows, columns=EXOGENOUS_COLUMNS)

    def test_fractional_exogenous_and_integer_endogenous_costs_no_double_count(self):
        tech, profile = self.inputs()
        profile['Beban (MW)'] = 12.
        exo = self.table([(2026, 'PLTG', 7.)])
        r = solve_multiyear(tech, profile, planning_years=2, capacity_model='integer', exogenous_additions=exo)
        np.testing.assert_allclose(r.capacity_plan['Kapasitas (MW)'], [12., 12.])
        np.testing.assert_allclose(r.capacity_plan['Kapasitas eksogen (MW)'], [7., 0.])
        np.testing.assert_allclose(r.capacity_plan['Kapasitas endogen (MW)'], [5., 0.])
        np.testing.assert_allclose(r.capacity_plan['Jumlah blok'], [1, 0])
        np.testing.assert_allclose(r.capacity_plan['Kapasitas tahun dasar (MW)'], 0.)
        self.assertAlmostEqual(r.capacity_plan['Investasi awal (USD)'].sum(), 12.*700.*1000.)
        for yr in r.year_results.values():
            self.assertAlmostEqual(yr.annual_cost, yr.summary[['Biaya tetap (USD/tahun)', 'Biaya operasi (USD/tahun)', 'Biaya karbon (USD/tahun)']].to_numpy().sum())
        self.assertAlmostEqual(r.npv_cost, sum(yr.annual_cost/1.08**(year-2025) for year, yr in r.year_results.items()))

    def test_future_projects_reduce_future_building_but_cannot_supply_before_operation(self):
        tech, profile = self.inputs()
        annual = {2026: profile.copy(), 2027: profile.assign(**{'Beban (MW)': [20.]}), 2028: profile.assign(**{'Beban (MW)': [30.]})}
        exo = self.table([(2027, 'PLTG', 20.)])
        for model in ['continuous', 'integer']:
            r = solve_multiyear(tech, profile, planning_years=3, annual_profiles=annual, exogenous_additions=exo, capacity_model=model)
            np.testing.assert_allclose(r.capacity_plan['Kapasitas endogen (MW)'], [10., 0., 0.], atol=1e-7)
            np.testing.assert_allclose(r.capacity_plan['Kapasitas eksogen (MW)'], [0., 20., 0.])
            np.testing.assert_allclose(r.capacity_plan['Kapasitas awal tahun (MW)'], [0., 10., 30.])

    def test_fixed_project_remains_even_if_not_economic_and_cost_starts_in_operation_year(self):
        tech, profile = self.inputs()
        tech['Kapasitas tahun dasar (MW)'] = 10.
        r = solve_multiyear(tech, profile, planning_years=2, exogenous_additions=self.table([(2027, 'PLTG', 15.)]))
        np.testing.assert_allclose(r.capacity_plan['Kapasitas (MW)'], [10., 25.])
        np.testing.assert_allclose(r.capacity_plan['Kapasitas endogen (MW)'], [0., 0.])
        self.assertEqual(r.capacity_plan['Investasi tahunan (USD/tahun)'].iloc[0], 0.)
        self.assertGreater(r.capacity_plan['Investasi tahunan (USD/tahun)'].iloc[1], 0.)

    def test_invalid_schedule_and_future_capacity_conflict(self):
        tech, profile = self.inputs()
        for row in [(2025, 'PLTG', 5.), (2028, 'PLTG', 5.), (2026, 'PLTS', 5.), (2026, 'PLTG', -1.), (2026.5, 'PLTG', 1.)]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate_exogenous(self.table([row]), tech, 2025, 2)
        tech['Batas kapasitas (MW)'] = 10.
        with self.assertRaises(ValueError):
            solve_multiyear(tech, profile, planning_years=2, exogenous_additions=self.table([(2027, 'PLTG', 11.)]))
        with self.assertRaises(InfeasibleModelError) as exc:
            solve_multiyear(tech, profile, planning_years=2, exogenous_additions=self.table([(2027, 'PLTG', 10.)]))
        self.assertTrue(any('lebih awal' in f for f in exc.exception.diagnosis['findings']))

    def test_stochastic_projects_are_shared_and_scenario_costs_included(self):
        tech, profile = self.inputs()
        exo = self.table([(2026, 'PLTG', 7.), (2026, 'PLTG', 3.)])
        scenarios = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.25, .75],
            'Faktor beban': [1., 2.], 'Pembangkit PLTG · Investasi (USD/kW)': [100., 200.]})
        r = solve_stochastic(tech, profile, scenarios, problem_builder=build_multiyear_problem,
            planning_years=2, exogenous_additions=exo, capacity_model='integer')
        for case in r.scenario_results.values():
            np.testing.assert_allclose(case.capacity_plan['Kapasitas eksogen (MW)'], [10., 0.])
            np.testing.assert_allclose(case.capacity_plan['Kapasitas endogen (MW)'], [10., 0.])
        self.assertAlmostEqual(r.npv_cost, .25*r.scenario_results['A'].npv_cost+.75*r.scenario_results['B'].npv_cost)

    def test_excel_new_sheet_and_old_workbook_without_sheet(self):
        self.assertTrue(read_excel_inputs(TEMPLATE_PATH.read_bytes()).snapshot['exogenous_inputs'].empty)
        frames = default_template_frames()
        frames['Kapasitas Eksogen'] = self.table([(2027, 'PLTG', 17.)])
        s = validate_excel_frames(frames).snapshot
        self.assertEqual(s['exogenous_inputs']['Tambahan eksogen (MW)'].iloc[0], 17.)
        del frames['Kapasitas Eksogen']
        self.assertTrue(validate_excel_frames(frames).snapshot['exogenous_inputs'].empty)


class ExogenousAppTests(unittest.TestCase):
    def click(self, app, label):
        next(w for w in app.button if w.label == label).click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)

    def test_single_year_project_copy_delete_and_rerun(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.session_state['exogenous_editor_0'] = {'edited_rows': {}, 'added_rows': [
            {'Tahun operasi': 2026, 'Teknologi': 'PLTG', 'Tambahan eksogen (MW)': 17.}], 'deleted_rows': []}
        app.run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        result = app.session_state['optimization']['result']
        self.assertEqual(result.capacity_plan['Kapasitas eksogen (MW)'].sum(), 17.)
        app.text_input(key='new_case_name').set_value('Proyek alternatif')
        self.click(app, 'Tambah Skenario')
        self.assertEqual(app.session_state['exogenous_inputs']['Tambahan eksogen (MW)'].sum(), 17.)
        self.click(app, 'Hapus Teknologi')
        next(w for w in app.selectbox if w.label == 'Teknologi yang akan dihapus').set_value(('generator', 'PLTG'))
        self.click(app, 'Hapus dari skenario aktif')
        self.assertTrue(app.session_state['exogenous_inputs'].empty)
        self.click(app, 'Jalankan Optimisasi')
        app.selectbox(key='case_picker').set_value('base').run(timeout=30)
        self.assertEqual(app.session_state['exogenous_inputs']['Tambahan eksogen (MW)'].sum(), 17.)


if __name__ == '__main__':
    unittest.main()
