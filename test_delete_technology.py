import unittest
from copy import deepcopy

import pandas as pd
from streamlit.testing.v1 import AppTest

from model import BatteryConfig, add_technology, example_inputs
from storage_inputs import add_storage, empty_storage_table
from technology_management import remove_technology


class DeleteTechnologyTests(unittest.TestCase):
    def state(self):
        tech, profile = example_inputs()
        tech, profile = add_technology(tech, profile, 'PLTU Baru', 1000., 10., 10., .1, 0., 20., 10., .9)
        return {'technology_inputs_v2': tech, 'profile_inputs_v2': profile,
                'storage_inputs': empty_storage_table(),
                'annual_availabilities': {2027: profile.drop(columns='Beban (MW)').copy()},
                'uncertain_parameters': ['Faktor PLTU', 'Faktor PLTU Baru', 'Pembangkit PLTU · Investasi (USD/kW)', 'Faktor beban'],
                'stochastic_inputs': pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.4, .6],
                    'Faktor PLTU': [1., .8], 'Faktor PLTU Baru': [.9, 1.],
                    'Pembangkit PLTU · Investasi (USD/kW)': [1000., 2000.], 'Faktor beban': [1., 1.1]})}

    def test_generator_removes_only_owned_data_and_keeps_probabilities(self):
        state = self.state()
        original = deepcopy(state)
        remove_technology(state, 'PLTU')
        self.assertNotIn('PLTU', state['technology_inputs_v2'].Teknologi.tolist())
        self.assertNotIn('PLTU', state['profile_inputs_v2'])
        self.assertNotIn('PLTU', state['annual_availabilities'][2027])
        self.assertNotIn('Faktor PLTU', state['stochastic_inputs'])
        self.assertNotIn('Pembangkit PLTU · Investasi (USD/kW)', state['uncertain_parameters'])
        self.assertIn('Faktor PLTU Baru', state['uncertain_parameters'])
        self.assertTrue(state['stochastic_inputs'].Probabilitas.equals(original['stochastic_inputs'].Probabilitas))
        self.assertIn('PLTU', original['profile_inputs_v2'])

    def test_storage_removal_cleans_uncertainty_and_leaves_generators(self):
        state = self.state()
        state['storage_inputs'] = add_storage(state['storage_inputs'], 'Flow', BatteryConfig(), state['technology_inputs_v2'].Teknologi)
        label = 'Penyimpanan Flow · Investasi daya (USD/kW)'
        state['uncertain_parameters'].append(label)
        state['stochastic_inputs'][label] = [100., 200.]
        remove_technology(state, 'Flow', 'storage')
        self.assertTrue(state['storage_inputs'].empty)
        self.assertNotIn(label, state['stochastic_inputs'])
        self.assertNotIn(label, state['uncertain_parameters'])
        self.assertEqual(len(state['technology_inputs_v2']), 5)

    def test_last_generator_and_unknown_name_are_rejected_without_mutation(self):
        state = self.state()
        state['technology_inputs_v2'] = state['technology_inputs_v2'].iloc[:1].copy()
        for name in ['PLTU', 'Tidak ada']:
            with self.assertRaises(ValueError):
                remove_technology(state, name)
            self.assertEqual(state['technology_inputs_v2'].Teknologi.tolist(), ['PLTU'])
            self.assertIn('PLTU', state['profile_inputs_v2'])


class DeleteTechnologyAppTests(unittest.TestCase):
    def click(self, app, label):
        next(w for w in app.button if w.label == label).click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)

    def delete(self, app, name, kind='generator'):
        self.click(app, 'Hapus Teknologi')
        next(w for w in app.selectbox if w.label == 'Teknologi yang akan dihapus').set_value((kind, name))
        self.click(app, 'Hapus dari skenario aktif')

    def test_stochastic_deletion_requires_rerun_and_is_isolated_to_active_scenario(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        app.number_input(key='planning_years').set_value(2)
        app.checkbox(key='stochastic_enabled').check().run(timeout=30)
        app.multiselect(key='uncertain_parameters').set_value(['Faktor beban', 'Faktor PLTU', 'Pembangkit PLTU · Investasi (USD/kW)']).run(timeout=30)
        app.text_input(key='new_case_name').set_value('Tanpa PLTU')
        self.click(app, 'Tambah Skenario')
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(len(app.metric), 3)
        self.delete(app, 'PLTU')
        self.assertEqual(len(app.metric), 0)
        self.assertNotIn('PLTU', app.session_state['profile_inputs_v2'])
        self.assertNotIn('Faktor PLTU', app.session_state['uncertain_parameters'])
        self.assertNotIn('Faktor PLTU', app.session_state['stochastic_inputs'])
        self.click(app, 'Jalankan Optimisasi')
        self.assertNotIn('PLTU', app.session_state['optimization']['result'].summary.Teknologi.tolist())
        app.selectbox(key='case_picker').set_value('base').run(timeout=30)
        self.assertIn('PLTU', app.session_state['technology_inputs_v2'].Teknologi.tolist())
        self.assertIn('Faktor PLTU', app.session_state['uncertain_parameters'])

    def test_add_delete_storage_and_run_again(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        self.click(app, 'Tambah Teknologi')
        next(w for w in app.selectbox if w.label == 'Jenis teknologi baru').set_value('Penyimpanan energi').run(timeout=30)
        next(w for w in app.text_input if w.label == 'Nama penyimpanan baru').set_value('Flow')
        self.click(app, 'Tambahkan penyimpanan ke model')
        self.delete(app, 'Flow', 'storage')
        self.assertTrue(app.session_state['storage_inputs'].empty)
        self.click(app, 'Jalankan Optimisasi')
        self.assertEqual(app.session_state['optimization']['result'].storage_summary.Teknologi.tolist(), ['Baterai'])


if __name__ == '__main__':
    unittest.main()
