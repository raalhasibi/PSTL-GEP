import unittest

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from model import example_inputs
from multiyear import build_multiyear_problem, solve_multiyear
from stochastic import solve_stochastic
from year_profiles import LOAD_PERCENT, make_annual_profiles, validate_shape


class YearProfileTests(unittest.TestCase):
    def inputs(self):
        tech, _ = example_inputs()
        tech = tech.iloc[[1]].copy()
        profile = pd.DataFrame({'Jam': [0, 1], 'Beban (MW)': [50., 100.], 'PLTG': [1., 1.]})
        shape = pd.DataFrame({'Jam': [0, 1], LOAD_PERCENT: [50., 100.]})
        changed = pd.DataFrame({'Jam': [0, 1], LOAD_PERCENT: [100., 20.]})
        a = pd.DataFrame({'Jam': [0, 1], 'PLTG': [.5, .75]})
        return tech, profile, shape, changed, a

    def test_year_specific_shapes_availability_and_inheritance(self):
        tech, base, shape, changed, a = self.inputs()
        frames = make_annual_profiles(base, shape, {2026: 200., 2027: 120.}, {2026: changed}, {2026: a})
        np.testing.assert_allclose(frames[2026]['Beban (MW)'], [200., 40.])
        np.testing.assert_allclose(frames[2027]['Beban (MW)'], [60., 120.])
        np.testing.assert_allclose(frames[2026].PLTG, [.5, .75])
        np.testing.assert_allclose(frames[2027].PLTG, [1., 1.])
        r = solve_multiyear(tech, base, planning_years=2, annual_profiles=frames)
        self.assertAlmostEqual(r.year_results[2026].annual_energy, 240.*365)
        self.assertAlmostEqual(r.year_results[2027].annual_energy, 180.*365)
        np.testing.assert_allclose(r.capacity_plan['Kapasitas (MW)'], [400., 400.])

    def test_stochastic_factors_apply_to_each_year_without_mutating_inputs(self):
        tech, base, shape, changed, a = self.inputs()
        frames = make_annual_profiles(base, shape, {2026: 200., 2027: 120.}, {2026: changed}, {2026: a})
        scenarios = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.5, .5], 'Faktor beban': [1., 1.1], 'Faktor PLTG': [1., .5]})
        r = solve_stochastic(tech, base, scenarios, problem_builder=build_multiyear_problem, planning_years=2, annual_profiles=frames)
        np.testing.assert_allclose(r.scenario_results['B'].year_results[2026].dispatch['Beban (MW)'], [220., 44.])
        self.assertAlmostEqual(r.capacity_plan['Kapasitas (MW)'].iloc[0], 880.)
        np.testing.assert_allclose(frames[2026].PLTG, [.5, .75])
        np.testing.assert_allclose(frames[2026]['Beban (MW)'], [200., 40.])

    def test_validation_and_new_technology_inherits_base_availability(self):
        _, base, shape, _, a = self.inputs()
        for values in [[50., 90.], [101., 100.], [-1., 100.], [np.nan, 100.]]:
            with self.assertRaises(ValueError):
                validate_shape(pd.DataFrame({'Jam': [0, 1], LOAD_PERCENT: values}), [0, 1])
        base['PLTP'] = [.8, .9]
        frames = make_annual_profiles(base, shape, {2026: 100.}, availabilities={2026: a})
        np.testing.assert_allclose(frames[2026].PLTP, [.8, .9])


class YearProfileAppTests(unittest.TestCase):
    def click(self, app, label):
        next(w for w in app.button if w.label == label).click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)

    def test_separate_editors_year_override_and_scenario_restore(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.number_input(key='planning_years').set_value(2).run(timeout=30)
        app.selectbox(key='load_shape_mode').set_value('Edit per tahun').run(timeout=30)
        app.selectbox(key='availability_mode').set_value('Edit per tahun').run(timeout=30)
        app.session_state['load_shape_editor_2026_0'] = {'edited_rows': {0: {LOAD_PERCENT: 100.}}, 'added_rows': [], 'deleted_rows': []}
        app.session_state['availability_editor_2026_0'] = {'edited_rows': {0: {'PLTG': .2}}, 'added_rows': [], 'deleted_rows': []}
        app.run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        r = app.session_state['optimization']['result']
        self.assertEqual(r.year_results[2026].dispatch['Beban (MW)'].iloc[0], 100.)
        self.assertEqual(r.year_results[2027].dispatch['Beban (MW)'].iloc[0], 60.)
        app.text_input(key='new_case_name').set_value('Profil alternatif')
        self.click(app, 'Tambah Skenario')
        revision = app.session_state['input_revision_v2']
        app.session_state[f'load_shape_editor_2026_{revision}'] = {'edited_rows': {0: {LOAD_PERCENT: 90.}}, 'added_rows': [], 'deleted_rows': []}
        app.run(timeout=30)
        self.assertEqual(app.session_state['annual_load_shapes'][2026][LOAD_PERCENT].iloc[0], 90.)
        app.selectbox(key='case_picker').set_value('base').run(timeout=30)
        self.assertEqual(app.session_state['annual_load_shapes'][2026][LOAD_PERCENT].iloc[0], 100.)
        self.assertEqual(app.session_state['annual_availabilities'][2026].PLTG.iloc[0], .2)
        app.selectbox(key='load_shape_mode').set_value('Gunakan data tahun dasar').run(timeout=30)
        self.assertEqual(len(app.metric), 0)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(app.session_state['optimization']['result'].year_results[2026].dispatch['Beban (MW)'].iloc[0], 60.)
        self.assertEqual(app.session_state['annual_load_shapes'][2026][LOAD_PERCENT].iloc[0], 100.)


if __name__ == '__main__':
    unittest.main()
