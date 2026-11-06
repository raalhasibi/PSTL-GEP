import unittest

from streamlit.testing.v1 import AppTest


class ScenarioTests(unittest.TestCase):
    def click(self, app, label):
        next(w for w in app.button if w.label == label).click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)

    def create(self, app, name, source='base'):
        app.selectbox(key='case_source').set_value(source)
        app.text_input(key='new_case_name').set_value(name)
        self.click(app, 'Tambah Skenario')
        return app.session_state['active_case']

    def switch(self, app, target):
        app.selectbox(key='case_picker').set_value(target).run(timeout=30)
        self.assertEqual(len(app.exception), 0)

    def test_copy_isolation_cached_results_and_comparison(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.session_state['technology_v2_0'] = {'edited_rows': {0: {'Kapasitas tahun dasar (MW)': 35.}}, 'added_rows': [], 'deleted_rows': []}
        app.session_state['availability_editor_base_0'] = {'edited_rows': {0: {'PLTU': .7}}, 'added_rows': [], 'deleted_rows': []}
        app.number_input(key='planning_years').set_value(5).run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        base_cost = app.session_state['optimization']['result'].annual_cost
        child = self.create(app, 'Harga karbon tinggi')
        self.assertNotEqual(child, 'base')
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(app.number_input(key='planning_years').value, 5)
        self.assertEqual(app.session_state['technology_inputs_v2']['Kapasitas tahun dasar (MW)'].iloc[0], 35.)
        self.assertEqual(app.session_state['profile_inputs_v2'].PLTU.iloc[0], .7)
        app.number_input(key='carbon_input').set_value(100.)
        revision = app.session_state['input_revision_v2']
        app.session_state[f'technology_v2_{revision}'] = {'edited_rows': {0: {'Kapasitas tahun dasar (MW)': 55.}}, 'added_rows': [], 'deleted_rows': []}
        app.run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        child_cost = app.session_state['optimization']['result'].annual_cost
        self.assertNotEqual(child_cost, base_cost)
        self.switch(app, 'base')
        self.assertEqual(app.number_input(key='carbon_input').value, 0.)
        self.assertEqual(app.session_state['technology_inputs_v2']['Kapasitas tahun dasar (MW)'].iloc[0], 35.)
        self.assertEqual(app.session_state['optimization']['result'].annual_cost, base_cost)
        self.assertEqual(len(app.metric), 3)
        self.switch(app, child)
        self.assertEqual(app.number_input(key='carbon_input').value, 100.)
        self.assertEqual(app.session_state['technology_inputs_v2']['Kapasitas tahun dasar (MW)'].iloc[0], 55.)
        self.assertEqual(app.session_state['optimization']['result'].annual_cost, child_cost)
        app.number_input(key='carbon_input').set_value(200.).run(timeout=30)
        self.assertEqual(len(app.metric), 0)
        overview = next(t.value for t in app.dataframe if 'Status' in t.value.columns)
        self.assertEqual(overview.set_index('Skenario').loc['Harga karbon tinggi', 'Status'], 'Input berubah')
        self.switch(app, 'base')
        self.assertEqual(len(app.metric), 3)

    def test_names_copy_from_child_and_delete(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.create(app, '  ')
        self.assertEqual(len(app.session_state['experiment_cases']), 1)
        self.assertTrue(any('nama skenario' in e.value.lower() for e in app.error))
        self.create(app, 'skenario DASAR')
        self.assertEqual(len(app.session_state['experiment_cases']), 1)
        child = self.create(app, 'A')
        app.number_input(key='carbon_input').set_value(77.).run(timeout=30)
        grandchild = self.create(app, 'B', source=child)
        self.assertEqual(app.number_input(key='carbon_input').value, 77.)
        self.assertEqual(app.session_state['experiment_cases'][grandchild]['source'], 'A')
        self.click(app, 'Hapus skenario aktif')
        self.assertEqual(app.session_state['active_case'], 'base')
        self.assertEqual(len(app.session_state['experiment_cases']), 2)
        self.assertTrue(next(w for w in app.button if w.label == 'Hapus skenario aktif').disabled)

    def test_storage_and_stochastic_inputs_are_cloned_and_restored(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.radio[0].set_value('Blok integer + penyimpanan (MILP)').run(timeout=30)
        app.number_input(key='bat_existing').set_value(7.)
        app.number_input(key='bat_duration').set_value(6.)
        app.checkbox(key='stochastic_enabled').check().run(timeout=30)
        app.number_input(key='stochastic_count').set_value(4).run(timeout=30)
        key = app.session_state['stochastic_editor_key']
        app.session_state[key] = {'edited_rows': {0: {'Faktor beban': 1.37}}, 'added_rows': [], 'deleted_rows': []}
        app.run(timeout=30)
        self.click(app, 'Tambah Teknologi')
        next(w for w in app.selectbox if w.label == 'Jenis teknologi baru').select('Penyimpanan energi').run(timeout=30)
        next(w for w in app.text_input if w.label == 'Nama penyimpanan baru').set_value('Flow')
        self.click(app, 'Tambahkan penyimpanan ke model')
        child = self.create(app, 'Penyimpanan besar')
        self.assertEqual(app.number_input(key='bat_existing').value, 7.)
        self.assertEqual(len(app.session_state['storage_inputs']), 1)
        self.assertEqual(app.number_input(key='stochastic_count').value, 4)
        self.assertAlmostEqual(app.session_state['stochastic_inputs']['Faktor beban'].iloc[0], 1.37)
        app.number_input(key='bat_duration').set_value(9.).run(timeout=30)
        app.checkbox(key='stochastic_enabled').uncheck().run(timeout=30)
        app.radio[0].set_value('Kontinu (LP)').run(timeout=30)
        self.switch(app, 'base')
        self.assertEqual(app.radio[0].value, 'Blok integer + penyimpanan (MILP)')
        self.assertEqual(app.number_input(key='bat_duration').value, 6.)
        self.assertTrue(app.checkbox(key='stochastic_enabled').value)
        self.switch(app, child)
        app.radio[0].set_value('Blok integer + penyimpanan (MILP)').run(timeout=30)
        self.assertEqual(app.number_input(key='bat_duration').value, 9.)
        app.checkbox(key='stochastic_enabled').check().run(timeout=30)
        self.assertEqual(app.number_input(key='stochastic_count').value, 4)
        self.assertAlmostEqual(app.session_state['stochastic_inputs']['Faktor beban'].iloc[0], 1.37)


if __name__ == '__main__':
    unittest.main()
