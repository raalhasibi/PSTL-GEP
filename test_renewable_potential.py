import unittest

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from model import POTENTIAL_COLUMN, InfeasibleModelError, example_inputs, solve
from multiyear import solve_multiyear
from stochastic import solve_stochastic, StochasticInfeasibleError
from exogenous import EXOGENOUS_COLUMNS
from excel_inputs import default_template_frames, validate_excel_frames, ExcelInputError


class RenewablePotentialTests(unittest.TestCase):
    def inputs(self, load=10.):
        tech, _ = example_inputs()
        tech = tech.iloc[[2]].copy()
        tech['Ukuran blok (MW)'] = 5.
        return tech, pd.DataFrame({'Jam':[0], 'Beban (MW)':[load], 'PLTS':[1.]})

    def test_potential_and_general_limit_apply_together(self):
        tech, p = self.inputs(10.)
        tech[POTENTIAL_COLUMN] = 12.
        self.assertAlmostEqual(solve(tech, p).summary['Kapasitas (MW)'].iloc[0], 10.)
        tech['Batas kapasitas (MW)'] = 8.
        with self.assertRaises(InfeasibleModelError):
            solve(tech, p)
        tech['Batas kapasitas (MW)'] = 0.
        tech[POTENTIAL_COLUMN] = 8.
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(tech, p)
        self.assertEqual(exc.exception.diagnosis['capacity']['Batas efektif (MW)'].iloc[0], 8.)
        suggestions = exc.exception.diagnosis['suggestions']
        self.assertFalse(any(s['Parameter'].startswith('Batas kapasitas') for s in suggestions))
        repair = next(s for s in suggestions if s['Parameter'].startswith('Potensi EBT'))
        tech[POTENTIAL_COLUMN] = repair['Contoh nilai layak']
        solve(tech, p)
        tech[POTENTIAL_COLUMN] = 0.
        p['Beban (MW)'] = 500.
        self.assertAlmostEqual(solve(tech, p).summary['Kapasitas (MW)'].iloc[0], 500.)

    def test_integer_uses_remaining_potential_after_base_capacity(self):
        tech, p = self.inputs(9.)
        tech['Kapasitas tahun dasar (MW)'] = 3.
        tech[POTENTIAL_COLUMN] = 12.
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(tech, p, capacity_model='integer')
        self.assertAlmostEqual(exc.exception.diagnosis['capacity']['Batas efektif (MW)'].iloc[0], 8.)
        repair = next(s for s in exc.exception.diagnosis['suggestions'] if s['Parameter'].startswith('Ukuran blok'))
        r = solve(tech, p, capacity_model='integer', block_sizes={'PLTS': repair['Contoh nilai layak']})
        self.assertLessEqual(r.summary['Kapasitas (MW)'].iloc[0], 12.+1e-7)

    def test_no_single_parameter_repair_claimed_when_both_caps_bind(self):
        tech, p = self.inputs(100.)
        tech[POTENTIAL_COLUMN] = 80.
        tech['Batas kapasitas (MW)'] = 80.
        with self.assertRaises(InfeasibleModelError) as exc:
            solve(tech, p)
        self.assertEqual(exc.exception.diagnosis['suggestions'], [])

    def test_multiyear_exogenous_counts_and_conflicts(self):
        tech, p = self.inputs(6.)
        tech['Kapasitas tahun dasar (MW)'] = 2.
        tech[POTENTIAL_COLUMN] = 12.
        exo = pd.DataFrame([(2027,'PLTS',3.)], columns=EXOGENOUS_COLUMNS)
        annual = {2026:p.copy(),2027:p.assign(**{'Beban (MW)':[12.]})}
        r = solve_multiyear(tech,p,planning_years=2,annual_profiles=annual,exogenous_additions=exo)
        np.testing.assert_allclose(r.capacity_plan['Kapasitas (MW)'],[6.,12.])
        np.testing.assert_allclose(r.capacity_plan[POTENTIAL_COLUMN],12.)
        bad = pd.DataFrame([(2027,'PLTS',11.)],columns=EXOGENOUS_COLUMNS)
        with self.assertRaisesRegex(ValueError,'potensi EBT'):
            solve_multiyear(tech,p,planning_years=2,exogenous_additions=bad)
        # Kedua tahun sendiri layak, tetapi kebutuhan pembangunan awal
        # bertentangan dengan sisa potensi setelah proyek masa depan masuk.
        p['Beban (MW)'] = 12.
        with self.assertRaises(InfeasibleModelError) as exc:
            solve_multiyear(tech,p,planning_years=2,exogenous_additions=exo)
        self.assertTrue(any('potensi EBT' in f for f in exc.exception.diagnosis['findings']))

    def test_stochastic_and_validation(self):
        tech,p = self.inputs()
        tech[POTENTIAL_COLUMN] = 15.
        cases = pd.DataFrame({'Skenario':['A','B'],'Probabilitas':[.5,.5],'Faktor beban':[1.,1.2]})
        r = solve_stochastic(tech,p,cases)
        self.assertLessEqual(r.summary['Kapasitas (MW)'].iloc[0],15.)
        cases.loc[1,'Faktor beban'] = 1.6
        with self.assertRaises(StochasticInfeasibleError):
            solve_stochastic(tech,p,cases)
        for potential in [-1.,np.nan,np.inf]:
            tech[POTENTIAL_COLUMN] = potential
            with self.assertRaises(ValueError):
                solve(tech,p)

    def test_excel_backwards_compatibility_and_potential_validation(self):
        frames = default_template_frames()
        frames['Pembangkit'][POTENTIAL_COLUMN] = [0.,0.,100.,200.]
        self.assertEqual(validate_excel_frames(frames).snapshot['technology_inputs_v2'][POTENTIAL_COLUMN].iloc[2],100.)
        frames['Pembangkit'] = frames['Pembangkit'].drop(columns=POTENTIAL_COLUMN)
        self.assertTrue((validate_excel_frames(frames).snapshot['technology_inputs_v2'][POTENTIAL_COLUMN] == 0).all())
        frames['Pembangkit'][POTENTIAL_COLUMN] = [0.,0.,-1.,0.]
        with self.assertRaises(ExcelInputError):
            validate_excel_frames(frames)


class RenewablePotentialAppTests(unittest.TestCase):
    def test_potential_edit_invalidates_results_and_blocks_exogenous_overflow(self):
        app=AppTest.from_file('app.py').run(timeout=30)
        next(w for w in app.button if w.label=='Jalankan Optimisasi').click().run(timeout=30)
        app.session_state['technology_v2_0']={'edited_rows':{2:{POTENTIAL_COLUMN:5.}},'added_rows':[],'deleted_rows':[]}
        app.run(timeout=30)
        self.assertEqual(len(app.metric),0)
        next(w for w in app.button if w.label=='Jalankan Optimisasi').click().run(timeout=30)
        self.assertEqual(len(app.exception),0)
        r=app.session_state['optimization']['result']
        self.assertLessEqual(r.summary.loc[r.summary.Teknologi=='PLTS','Kapasitas (MW)'].iloc[0],5.+1e-6)
        app.session_state['exogenous_editor_0']={'edited_rows':{},'added_rows':[{
            'Tahun operasi':2026,'Teknologi':'PLTS','Tambahan eksogen (MW)':10.}],'deleted_rows':[]}
        app.run(timeout=30)
        next(w for w in app.button if w.label=='Jalankan Optimisasi').click().run(timeout=30)
        self.assertEqual(len(app.metric),0)
        self.assertTrue(any('potensi EBT' in e.value for e in app.error))


if __name__=='__main__':
    unittest.main()
