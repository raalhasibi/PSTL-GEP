"""Uji alur kelas melalui runtime Streamlit tanpa browser."""
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from model import example_inputs, solve


class AppTests(unittest.TestCase):
    def test_multiyear_year_selection_and_comparison_uses_final_year(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.number_input(key='planning_years').set_value(3)
        app.number_input(key='load_growth').set_value(5.).run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        plan = app.session_state['optimization']['result']
        self.assertEqual(list(plan.year_results), [2026, 2027, 2028])
        next(w for w in app.selectbox if w.label == 'Tahun untuk rincian hasil dan dispatch').set_value(2026).run(timeout=30)
        self.assertEqual(app.metric[0].value, f'{plan.year_results[2026].annual_cost/1e6:,.2f} juta USD/tahun')
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertAlmostEqual(app.session_state['saved'][0]['Biaya (juta USD/tahun)'], plan.annual_cost/1e6)
        self.assertAlmostEqual(app.session_state['saved'][0]['Nilai kini biaya periode (juta USD)'], plan.npv_cost/1e6)
        self.assertEqual(app.session_state['optimization']['result'].npv_cost, plan.npv_cost)

    def test_multiyear_stochastic_storage_year_details(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.radio[0].set_value('Blok integer + penyimpanan (MILP)')
        app.number_input(key='planning_years').set_value(2)
        app.checkbox(key='stochastic_enabled').check().run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        plan = app.session_state['optimization']['result']
        self.assertEqual(len(plan.year_results), 2)
        self.assertFalse(plan.storage_plan.empty)
        next(w for w in app.selectbox if w.label == 'Tahun untuk rincian hasil dan dispatch').set_value(2026).run(timeout=30)
        next(w for w in app.selectbox if w.label == 'Skenario untuk grafik dispatch').set_value('Berat').run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 6)

    @staticmethod
    def set_table_load(app, peak):
        # Fixtures kapasitas terbatas untuk pengujian infeasibilitas dan rerun.
        revision = app.session_state['input_revision_v2']
        app.session_state[f'technology_v2_{revision}'] = {'edited_rows': {
            i: {'Batas kapasitas (MW)': 300.} for i in range(len(app.session_state['technology_inputs_v2']))},
            'added_rows': [], 'deleted_rows': []}
        app.number_input(key='base_peak_mw').set_value(peak)
        app.run(timeout=30)

    def test_planning_years_affect_solver_and_preserve_base_load(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.number_input(key='base_year').set_value(2025)
        app.number_input(key='planning_years').set_value(5)
        app.number_input(key='load_growth').set_value(5.).run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        result = app.session_state['optimization']['result']
        self.assertAlmostEqual(result.dispatch['Beban (MW)'].max(), 100.*1.05**5)
        self.assertEqual(app.session_state['profile_inputs_v2']['Beban (MW)'].max(), 100.)
        self.assertEqual(app.session_state['optimization']['planning']['Tahun akhir'], 2030)
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertEqual(app.session_state['saved'][0]['Tahun akhir'], 2030)
        self.click(app, 'Jalankan Optimisasi')
        self.assertAlmostEqual(app.session_state['optimization']['result'].annual_energy, result.annual_energy)
        app.number_input(key='base_year').set_value(2026).run(timeout=30)
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any('Input berubah' in w.value for w in app.warning))
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(app.session_state['optimization']['planning']['Tahun akhir'], 2031)
        app.number_input(key='planning_years').set_value(10).run(timeout=30)
        self.assertEqual(len(app.metric), 0)

    def test_stochastic_factors_apply_after_year_projection(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.number_input(key='planning_years').set_value(2)
        app.number_input(key='load_growth').set_value(5.)
        next(w for w in app.checkbox if w.label == 'Aktifkan model stokastik dua tahap').check().run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        result = app.session_state['optimization']['result']
        self.assertAlmostEqual(result.scenario_results['Berat'].dispatch['Beban (MW)'].max(), 100.*1.05**2*1.1)

    def test_existing_capacity_editor_and_stale_results(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.session_state['technology_v2_0'] = {'edited_rows': {0: {'Kapasitas tahun dasar (MW)': 35.}}, 'added_rows': [], 'deleted_rows': []}
        app.run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        result = app.session_state['optimization']['result']
        self.assertEqual(result.summary['Kapasitas tahun dasar (MW)'].iloc[0], 35.)
        self.assertAlmostEqual(result.summary['Investasi awal (USD)'].iloc[0], result.summary['Kapasitas baru (MW)'].iloc[0]*1800.*1000.)
        app.session_state['technology_v2_0'] = {'edited_rows': {0: {'Kapasitas tahun dasar (MW)': 45.}}, 'added_rows': [], 'deleted_rows': []}
        app.run(timeout=30)
        self.assertEqual(len(app.metric), 0)

    @staticmethod
    def click(app, label):
        next(w for w in app.button if w.label == label).click().run(timeout=30)

    def test_default_save_and_clear(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 0)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.metric), 3)
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertEqual(len(app.session_state['saved']), 1)
        self.click(app, 'Hapus perbandingan')
        self.assertEqual(app.session_state['saved'], [])

    def test_infeasible_limit_shows_explanation(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.checkbox[0].check().run()
        self.set_table_load(app, 200.)
        next(w for w in app.number_input if w.label == 'Batas emisi (tCO2/tahun)').set_value(0.).run()
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertIn('Tidak ada solusi layak', app.error[0].value)
        self.assertTrue(any(h.value == 'Diagnosis infeasibilitas' for h in app.subheader))
        self.assertTrue(any('Contoh nilai layak' in table.value.columns for table in app.dataframe))
        self.assertIn('diagnosis', app.session_state['optimization'])

    def test_switch_models_and_save_comparison(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.click(app, 'Simpan hasil untuk perbandingan')
        app.radio[0].set_value('Blok integer (MILP)').run()
        self.assertEqual(len(app.metric), 0)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 3)
        self.assertTrue(any('Jumlah blok' in table.value.columns for table in app.dataframe))
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertEqual([s['Model'] for s in app.session_state['saved']],
                         ['Kontinu (LP)', 'Blok integer (MILP)'])
        app.radio[0].set_value('Kontinu (LP)').run()
        self.assertEqual(len(app.exception), 0)

    def test_battery_model_and_zero_capacity(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.radio[0].set_value('Blok integer + penyimpanan (MILP)').run(timeout=60)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 6)
        self.assertTrue(any('Energi (MWh)' in table.value.columns for table in app.dataframe))
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertEqual(app.session_state['saved'][0]['Model'], 'Blok integer + penyimpanan (MILP)')
        next(w for w in app.number_input if w.label == 'Batas daya baterai (MW)').set_value(0.).run(timeout=60)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('nol blok' in item.value for item in app.info))

    def test_solver_only_runs_on_button_and_stale_results_hidden(self):
        with patch('model.solve', wraps=solve) as solver:
            app = AppTest.from_file('app.py').run(timeout=30)
            solver.assert_not_called()
            self.click(app, 'Jalankan Optimisasi')
            self.assertEqual(solver.call_count, 1)
            original_cost = app.session_state['optimization']['result'].annual_cost
            self.click(app, 'Simpan hasil untuk perbandingan')
            self.assertEqual(solver.call_count, 1)
            self.set_table_load(app, 200.)
            self.assertEqual(solver.call_count, 1)
            self.assertEqual(len(app.metric), 0)
            self.assertTrue(any('Input berubah' in w.value for w in app.warning))
            self.assertFalse(any(w.label == 'Simpan hasil untuk perbandingan' for w in app.button))
            self.assertEqual(len(app.get('download_button')), 1)  # Template tetap dapat diunduh.
            self.click(app, 'Jalankan Optimisasi')
            self.assertEqual(solver.call_count, 2)
            self.assertEqual(len(app.metric), 3)
            self.assertNotEqual(app.session_state['optimization']['result'].annual_cost, original_cost)

    def test_failed_rerun_does_not_display_previous_success(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.set_table_load(app, 10000.)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 0)
        self.assertIn('Tidak ada solusi layak', app.error[0].value)

    def test_add_technology_preserves_edits_and_solves_all_modes(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.session_state['technology_v2_0'] = {'edited_rows': {0: {'Investasi (USD/kW)': 2222.}}, 'added_rows': [], 'deleted_rows': []}
        app.session_state['availability_editor_base_0'] = {'edited_rows': {0: {'PLTU': .7}}, 'added_rows': [], 'deleted_rows': []}
        app.run()
        self.click(app, 'Tambah Teknologi')
        next(w for w in app.text_input if w.label == 'Nama teknologi baru').set_value('PLTP')
        self.click(app, 'Tambahkan ke model')
        self.assertEqual(len(app.exception), 0)
        tech = app.session_state['technology_inputs_v2']
        profile = app.session_state['profile_inputs_v2']
        self.assertEqual(len(tech), 5)
        self.assertEqual(tech['Investasi (USD/kW)'].iloc[0], 2222.)
        self.assertAlmostEqual(profile['PLTU'].iloc[0], .7)
        self.assertTrue((profile.PLTP == .9).all())
        for mode in ['Kontinu (LP)', 'Blok integer (MILP)', 'Blok integer + penyimpanan (MILP)']:
            app.radio[0].set_value(mode).run()
            self.click(app, 'Jalankan Optimisasi')
            self.assertEqual(len(app.exception), 0)
            self.assertIn('PLTP', app.session_state['optimization']['result'].dispatch.columns)
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertIn('PLTP', app.session_state['saved'][0])
        self.assertIn('Investasi awal (juta USD)', app.session_state['saved'][0])

    def test_duplicate_technology_rejected(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.click(app, 'Tambah Teknologi')
        next(w for w in app.text_input if w.label == 'Nama teknologi baru').set_value('pltu')
        self.click(app, 'Tambahkan ke model')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state['technology_inputs_v2']), 4)
        self.assertTrue(any('unik' in error.value for error in app.error))

    def test_discount_change_requires_rerun(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        next(w for w in app.number_input if w.label == 'Tingkat diskonto (%)').set_value(0.).run()
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any('Input berubah' in w.value for w in app.warning))
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        result = app.session_state['optimization']['result']
        self.assertAlmostEqual(result.summary['CRF (1/tahun)'].iloc[0], 1/30)

    def test_stochastic_all_modes_and_scenario_selector_without_rerun(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        next(w for w in app.checkbox if w.label == 'Aktifkan model stokastik dua tahap').check().run()
        for mode in ['Kontinu (LP)', 'Blok integer (MILP)', 'Blok integer + penyimpanan (MILP)']:
            app.radio[0].set_value(mode).run()
            self.click(app, 'Jalankan Optimisasi')
            self.assertEqual(len(app.exception), 0)
            r = app.session_state['optimization']['result']
            self.assertEqual(len(r.scenario_results), 3)
            cost = r.annual_cost
            next(w for w in app.selectbox if w.label == 'Skenario untuk grafik dispatch').select('Berat').run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state['optimization']['result'].annual_cost, cost)
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertEqual(app.session_state['saved'][0]['Pendekatan'], 'Stokastik dua tahap')

    def test_stochastic_invalid_probability_and_per_scenario_diagnosis(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        next(w for w in app.checkbox if w.label == 'Aktifkan model stokastik dua tahap').check().run()
        app.session_state['stochastic_inputs_0'] = {'edited_rows': {0: {'Probabilitas': .5}}, 'added_rows': [], 'deleted_rows': []}
        app.run()
        self.click(app, 'Jalankan Optimisasi')
        self.assertTrue(any('probabilitas' in error.value.lower() for error in app.error))
        self.assertEqual(len(app.metric), 0)
        # Kembalikan probabilitas dan buat skenario pasti tidak layak.
        app.session_state['stochastic_inputs_0'] = {'edited_rows': {0: {'Probabilitas': .25}}, 'added_rows': [], 'deleted_rows': []}
        app.run()
        self.set_table_load(app, 10000.)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(w.label == 'Skenario untuk diagnosis' for w in app.selectbox))
        self.assertTrue(any('hanya berlaku untuk skenario terpilih' in w.value for w in app.warning))

    def add_storage(self, app, name):
        self.click(app, 'Tambah Teknologi')
        next(w for w in app.selectbox if w.label == 'Jenis teknologi baru').select('Penyimpanan energi').run()
        next(w for w in app.text_input if w.label == 'Nama penyimpanan baru').set_value(name)
        self.click(app, 'Tambahkan penyimpanan ke model')

    def test_add_multiple_storage_types_preserve_edits_and_stochastic(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.add_storage(app, 'Flow')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.radio[0].value, 'Blok integer + penyimpanan (MILP)')
        self.assertNotIn('Flow', app.session_state['profile_inputs_v2'])
        self.assertEqual(len(app.session_state['technology_inputs_v2']), 4)
        app.session_state['storage_inputs_1'] = {'edited_rows': {0: {'Durasi (jam)': 9.}}, 'added_rows': [], 'deleted_rows': []}
        app.run()
        self.add_storage(app, 'Pumped Hydro')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state['storage_inputs']['Durasi (jam)'].iloc[0], 9.)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        r = app.session_state['optimization']['result']
        self.assertEqual(r.storage_summary.Teknologi.tolist(), ['Baterai', 'Flow', 'Pumped Hydro'])
        self.assertEqual(len(app.metric), 6)
        next(w for w in app.selectbox if w.label == 'Penyimpanan untuk grafik energi').select('Flow').run()
        self.assertEqual(len(app.exception), 0)
        self.click(app, 'Simpan hasil untuk perbandingan')
        self.assertIn('Flow', app.session_state['saved'][0]['Penyimpanan per teknologi'])
        next(w for w in app.checkbox if w.label == 'Aktifkan model stokastik dua tahap').check().run()
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state['optimization']['result'].scenario_results), 3)

    def test_duplicate_storage_name_is_rejected(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.add_storage(app, 'Flow')
        self.add_storage(app, 'flow')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state['storage_inputs']), 1)
        self.assertTrue(any('unik' in error.value for error in app.error))

    def test_user_uncertain_parameters_and_scenario_count_preserve_values(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        next(w for w in app.checkbox if w.label == 'Aktifkan model stokastik dua tahap').check().run()
        next(w for w in app.multiselect if w.label == 'Parameter yang tidak pasti').set_value(['Faktor beban']).run()
        editor = app.session_state['stochastic_editor_key']
        app.session_state[editor] = {'edited_rows': {0: {'Faktor beban': 1.37}}, 'added_rows': [], 'deleted_rows': []}
        app.run()
        next(w for w in app.number_input if w.label == 'Jumlah skenario ketidakpastian').set_value(5).run()
        self.assertEqual(len(app.session_state['stochastic_inputs']), 5)
        self.assertAlmostEqual(app.session_state['stochastic_inputs']['Faktor beban'].iloc[0], 1.37)
        self.assertTrue((app.session_state['stochastic_inputs'].Probabilitas == .2).all())
        column = 'Pembangkit PLTG · Biaya variabel (USD/MWh)'
        next(w for w in app.multiselect if w.label == 'Parameter yang tidak pasti').set_value([column]).run()
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        result = app.session_state['optimization']['result']
        self.assertEqual(result.uncertainty_parameters, [column])
        self.assertEqual(len(result.scenario_results), 5)
        self.assertNotIn('Faktor beban', result.scenario_inputs)
        self.assertAlmostEqual(result.annual_energy, app.session_state['profile_inputs_v2']['Beban (MW)'].sum()*365)
        next(w for w in app.multiselect if w.label == 'Parameter yang tidak pasti').set_value(['Faktor beban', column]).run()
        self.assertEqual(len(app.metric), 0)
        self.assertAlmostEqual(app.session_state['stochastic_inputs']['Faktor beban'].iloc[0], 1.37)

    def test_user_two_scenarios_and_equal_probability_button(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        next(w for w in app.checkbox if w.label == 'Aktifkan model stokastik dua tahap').check().run()
        next(w for w in app.number_input if w.label == 'Jumlah skenario ketidakpastian').set_value(2).run()
        editor = app.session_state['stochastic_editor_key']
        app.session_state[editor] = {'edited_rows': {0: {'Probabilitas': .2}}, 'added_rows': [], 'deleted_rows': []}
        app.run()
        self.click(app, 'Jalankan Optimisasi')
        self.assertTrue(any('probabilitas' in error.value.lower() for error in app.error))
        self.click(app, 'Samakan probabilitas skenario')
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state['optimization']['result'].scenario_results), 2)
        self.assertTrue((app.session_state['stochastic_inputs'].Probabilitas == .5).all())


if __name__ == '__main__':
    unittest.main()
