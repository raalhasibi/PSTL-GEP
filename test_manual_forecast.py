import unittest

from streamlit.testing.v1 import AppTest


class ManualForecastTests(unittest.TestCase):
    def click(self, app, label):
        next(w for w in app.button if w.label == label).click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)

    def edit(self, app, values):
        app.session_state[app.session_state['manual_forecast_editor_key']] = {
            'edited_rows': {i: {'Puncak beban (MW)': value} for i, value in enumerate(values)},
            'added_rows': [], 'deleted_rows': []}
        app.run(timeout=30)

    def test_manual_multi_year_edit_and_independent_scenario_copy(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.number_input(key='planning_years').set_value(2).run(timeout=30)
        app.selectbox(key='load_projection_mode').set_value('Manual per tahun').run(timeout=30)
        self.edit(app, [130., 145.])
        self.click(app, 'Jalankan Optimisasi')
        result = app.session_state['optimization']['result']
        self.assertAlmostEqual(result.year_results[2026].dispatch['Beban (MW)'].max(), 130.)
        self.assertAlmostEqual(result.year_results[2027].dispatch['Beban (MW)'].max(), 145.)
        app.text_input(key='new_case_name').set_value('Beban tinggi')
        self.click(app, 'Tambah Skenario')
        self.assertEqual(app.selectbox(key='load_projection_mode').value, 'Manual per tahun')
        self.assertEqual(app.session_state['manual_forecast_inputs'][2027], 145.)
        self.edit(app, [150., 180.])
        self.assertEqual(len(app.metric), 0)
        app.selectbox(key='case_picker').set_value('base').run(timeout=30)
        self.assertEqual(app.session_state['manual_forecast_inputs'][2027], 145.)
        self.assertEqual(len(app.metric), 3)
        self.edit(app, [140., 160.])
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any('Input berubah' in w.value for w in app.warning))

    def test_manual_single_year_and_switch_back_to_growth(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.selectbox(key='load_projection_mode').set_value('Manual per tahun').run(timeout=30)
        self.edit(app, [170.])
        self.click(app, 'Jalankan Optimisasi')
        self.assertAlmostEqual(app.session_state['optimization']['result'].dispatch['Beban (MW)'].max(), 170.)
        app.selectbox(key='load_projection_mode').set_value('Pertumbuhan tahunan').run(timeout=30)
        self.click(app, 'Jalankan Optimisasi')
        self.assertAlmostEqual(app.session_state['optimization']['result'].dispatch['Beban (MW)'].max(), 100.)
        app.selectbox(key='load_projection_mode').set_value('Manual per tahun').run(timeout=30)
        self.assertEqual(app.session_state['manual_forecast_inputs'][2026], 170.)


if __name__ == '__main__':
    unittest.main()
