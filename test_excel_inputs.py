import unittest
from copy import deepcopy
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from excel_inputs import (AVAIL, ExcelInputError, TEMPLATE_PATH, default_template_frames,
                          read_excel_inputs, validate_excel_frames)
from excel_ui import apply_upload, check_upload
from scenario_manager import initialize
from year_profiles import LOAD_PERCENT


def setting(frames, label, value):
    frames['Pengaturan'].loc[frames['Pengaturan'].Parameter == label, 'Nilai'] = value


class ExcelInputTests(unittest.TestCase):
    def test_solver_options_have_no_credentials_and_old_files_default_to_highs(self):
        f = default_template_frames()
        setting(f, 'Solver optimisasi', 'Gurobi')
        setting(f, 'Lisensi Gurobi', 'Cloud (WLS)')
        s = validate_excel_frames(f).snapshot
        self.assertEqual(s['solver_choice'], 'Gurobi')
        self.assertEqual(s['gurobi_license_mode'], 'Cloud (WLS)')
        self.assertNotIn('gurobi_wls_secret', s)
        f['Pengaturan'] = f['Pengaturan'][~f['Pengaturan'].Parameter.isin(['Solver optimisasi', 'Lisensi Gurobi'])]
        self.assertEqual(validate_excel_frames(f).snapshot['solver_choice'], 'HiGHS')

    def test_downloaded_template_can_be_imported_without_solver(self):
        with patch('model.linprog') as solver:
            imported = read_excel_inputs(TEMPLATE_PATH.read_bytes())
        solver.assert_not_called()
        s = imported.snapshot
        self.assertEqual(s['planning_years'], 5)
        self.assertEqual(s['base_peak_mw'], 100.)
        self.assertEqual(len(s['technology_inputs_v2']), 4)
        self.assertEqual(len(s['base_load_shape']), 24)
        self.assertEqual(s['bat_eff'], 90.)

    def test_manual_year_profiles_stochastic_and_multiple_storages(self):
        f = default_template_frames()
        setting(f, 'Model kapasitas', 'Blok integer + penyimpanan (MILP)')
        setting(f, 'Aktifkan stokastik', 'YA')
        setting(f, 'Metode proyeksi beban', 'Manual per tahun')
        setting(f, 'Pola beban tahun berikutnya', 'Edit per tahun')
        setting(f, 'Availability tahun berikutnya', 'Edit per tahun')
        f['Beban Puncak'].loc[0, 'Puncak beban (MW)'] = 145.
        shape = f['Profil Beban'].copy()
        shape['Tahun'] = 2026
        shape.loc[0, LOAD_PERCENT] = 100.
        f['Profil Beban'] = pd.concat([f['Profil Beban'], shape], ignore_index=True)
        availability = f['Availability'][f['Availability'].Teknologi == 'PLTG'].copy()
        availability['Tahun'] = 2026
        availability[AVAIL] = .5
        f['Availability'] = pd.concat([f['Availability'], availability], ignore_index=True)
        extra = f['Penyimpanan'].copy()
        extra['Teknologi'] = 'Flow'
        f['Penyimpanan'] = pd.concat([f['Penyimpanan'], extra], ignore_index=True)
        s = validate_excel_frames(f).snapshot
        self.assertEqual(s['manual_forecast_inputs'][2026], 145.)
        self.assertEqual(s['annual_load_shapes'][2026][LOAD_PERCENT].iloc[0], 100.)
        self.assertEqual(s['annual_availabilities'][2026].PLTG.iloc[0], .5)
        self.assertEqual(s['storage_inputs'].Teknologi.tolist(), ['Flow'])
        self.assertTrue(s['stochastic_enabled'])
        self.assertEqual(s['stochastic_inputs'].Probabilitas.sum(), 1.)

    def test_errors_identify_sheet_and_do_not_accept_missing_numbers(self):
        mutations = [
            ('Pembangkit', lambda f: f['Pembangkit'].__setitem__('Investasi (USD/kW)', np.nan)),
            ('Pembangkit', lambda f: f['Pembangkit'].__setitem__('Teknologi', ['A', 'a', 'B', 'C'])),
            ('Profil Beban', lambda f: f['Profil Beban'].__setitem__(LOAD_PERCENT, 90.)),
            ('Availability', lambda f: f['Availability'].__setitem__(AVAIL, 2.)),
            ('Availability', lambda f: f['Availability'].__setitem__('Jam', 0)),
            ('Stokastik', lambda f: f['Stokastik'].__setitem__('Probabilitas', .2)),
        ]
        for sheet, mutate in mutations:
            with self.subTest(sheet=sheet):
                f = default_template_frames()
                mutate(f)
                with self.assertRaises(ExcelInputError) as exc:
                    validate_excel_frames(f)
                self.assertEqual(exc.exception.errors[0]['Sheet'], sheet)
                self.assertGreaterEqual(exc.exception.errors[0]['Baris'], 1)

    def test_missing_sheet_manual_year_and_unknown_parameter_are_rejected(self):
        f = default_template_frames()
        del f['Penyimpanan']
        with self.assertRaises(ExcelInputError):
            validate_excel_frames(f)
        f = default_template_frames()
        setting(f, 'Metode proyeksi beban', 'Manual per tahun')
        f['Beban Puncak'] = f['Beban Puncak'].iloc[:-1]
        with self.assertRaises(ExcelInputError):
            validate_excel_frames(f)
        f = default_template_frames()
        f['Stokastik'].loc[0, 'Parameter'] = 'Tidak dikenal'
        with self.assertRaises(ExcelInputError):
            validate_excel_frames(f)
        with self.assertRaises(ExcelInputError):
            read_excel_inputs(b'not an xlsx')

    def test_apply_is_atomic_and_checks_file_and_active_scenario(self):
        state = {}
        initialize(state)
        state['carbon_input'] = 123.
        state['optimization'] = {'old': 'result'}
        state['experiment_cases']['other'] = {'name': 'Lain', 'source': None, 'snapshot': {'carbon_input': 999.}}
        other = deepcopy(state['experiment_cases']['other'])
        self.assertFalse(check_upload(state, b'bad'))
        self.assertEqual(state['carbon_input'], 123.)
        self.assertEqual(state['optimization'], {'old': 'result'})
        data = TEMPLATE_PATH.read_bytes()
        self.assertTrue(check_upload(state, data))
        self.assertFalse(apply_upload(state, b'changed'))
        self.assertEqual(state['carbon_input'], 123.)
        self.assertTrue(apply_upload(state, data))
        self.assertEqual(state['carbon_input'], 0.)
        self.assertNotIn('optimization', state)
        self.assertEqual(state['experiment_cases']['other'], other)


class ExcelAppTests(unittest.TestCase):
    def test_template_button_and_import_apply_then_optimize(self):
        script = """
from pathlib import Path
import streamlit as st
from excel_inputs import TEMPLATE_PATH
from excel_ui import check_upload, apply_upload
from scenario_manager import initialize
initialize(st.session_state)
if st.session_state.pop('_test_apply', False):
    data = TEMPLATE_PATH.read_bytes()
    check_upload(st.session_state, data)
    apply_upload(st.session_state, data)
__file__ = str(Path('app.py').resolve())
exec(Path(__file__).read_text(encoding='utf-8'))
"""
        app = AppTest.from_string(script).run(timeout=30)
        self.assertTrue(any(w.label == 'Unduh Template Excel' for w in app.get('download_button')))
        app.session_state['_test_apply'] = True
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.number_input(key='planning_years').value, 5)
        self.assertEqual(len(app.metric), 0)
        next(w for w in app.button if w.label == 'Jalankan Optimisasi').click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state['optimization']['result'].year_results), 5)


if __name__ == '__main__':
    unittest.main()
