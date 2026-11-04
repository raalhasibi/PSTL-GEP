"""Skenario eksperimen independen dalam satu sesi; tanpa menjalankan solver."""
from copy import deepcopy
from uuid import uuid4


CONTROL_KEYS = {
    'base_year', 'planning_years', 'load_growth', 'capacity_model_choice',
    'carbon_input', 'discount_input', 'emissions_enabled', 'emissions_input',
    'stochastic_enabled', 'uncertain_parameters', 'stochastic_count',
    'bat_block', 'bat_duration', 'bat_max', 'bat_existing', 'bat_eff',
    'bat_capex_power', 'bat_capex_energy', 'bat_lifetime', 'bat_om_power_v2',
    'bat_om_energy_v2', 'bat_variable',
    'load_projection_mode',
    'base_peak_mw', 'load_shape_mode', 'availability_mode',
}
DATA_KEYS = {
    'technology_inputs_v2', 'profile_inputs_v2',
    'input_revision_v2', 'storage_inputs', 'storage_revision',
    'stochastic_inputs', 'stochastic_editor_revision', 'stochastic_layout',
    'optimization', 'input_signature',
    'manual_forecast_inputs', 'manual_forecast_layout', 'manual_forecast_revision',
    'base_load_shape', 'annual_load_shapes', 'annual_availabilities',
    'exogenous_inputs',
}
SNAPSHOT_KEYS = CONTROL_KEYS | DATA_KEYS
EDITOR_PREFIXES = ('technology_v2_', 'profiles_v2_', 'storage_inputs_', 'stochastic_inputs_', 'manual_forecast_editor_',
                   'load_shape_editor_', 'availability_editor_', 'exogenous_editor_')


def initialize(state):
    if 'experiment_cases' not in state:
        state['experiment_cases'] = {'base': {'name': 'Skenario dasar', 'source': None, 'snapshot': {}}}
        state['active_case'] = 'base'
        state['case_picker'] = 'base'
    # Streamlit membersihkan state widget yang tidak dirender. Pertahankan input
    # baterai/stokastik yang sementara disembunyikan saat mode dinonaktifkan.
    snapshot = state['experiment_cases'][state['active_case']]['snapshot']
    for key in CONTROL_KEYS:
        if key not in state and key in snapshot:
            state[key] = deepcopy(snapshot[key])


def save_active(state):
    case = state['experiment_cases'][state['active_case']]
    snapshot = deepcopy(case['snapshot'])
    snapshot.update({key: deepcopy(state[key]) for key in SNAPSHOT_KEYS if key in state})
    case['snapshot'] = snapshot


def restore(state, case_id):
    snapshot = deepcopy(state['experiment_cases'][case_id]['snapshot'])
    revisions = {key: max(state.get(key, 0), snapshot.get(key, 0))+1
                 for key in ('input_revision_v2', 'storage_revision', 'stochastic_editor_revision', 'manual_forecast_revision')}
    for key in list(state):
        if key in SNAPSHOT_KEYS or key.startswith(EDITOR_PREFIXES) or key in {
                'adding_technology', 'deleting_technology', 'technology_notice', 'activate_storage_model', 'stochastic_editor_key'}:
            del state[key]
    for key, value in snapshot.items():
        state[key] = value
    for key, value in revisions.items():
        state[key] = value
    state.pop('stochastic_layout', None)
    state['active_case'] = case_id
    state['case_picker'] = case_id


def switch_active(state):
    target = state['case_picker']
    if target != state['active_case']:
        save_active(state)
        restore(state, target)


def create_case(state):
    name = state.get('new_case_name', '').strip()
    cases = state['experiment_cases']
    if not name or len(name) > 100:
        state['case_error'] = 'Isi nama skenario baru (1–100 karakter).'
        return
    if name.casefold() in {case['name'].casefold() for case in cases.values()}:
        state['case_error'] = 'Nama skenario harus unik.'
        return
    save_active(state)
    source = state.get('case_source', 'base')
    snapshot = deepcopy(cases[source]['snapshot'])
    # Salin input saja: hasil harus dihitung sendiri untuk skenario baru.
    snapshot.pop('optimization', None)
    snapshot.pop('input_signature', None)
    case_id = uuid4().hex
    cases[case_id] = {'name': name, 'source': cases[source]['name'], 'snapshot': snapshot}
    restore(state, case_id)
    state['new_case_name'] = ''
    state.pop('case_error', None)


def delete_active(state):
    case_id = state['active_case']
    if case_id == 'base':
        return
    restore(state, 'base')
    del state['experiment_cases'][case_id]
    if state.get('case_source') == case_id:
        state['case_source'] = 'base'
    state.pop('case_error', None)


def case_overview(state):
    """Hanya hasil yang sesuai input tersimpan dianggap valid."""
    rows = []
    for case in state['experiment_cases'].values():
        snapshot = case['snapshot']
        calculation = snapshot.get('optimization', {})
        current = calculation.get('signature') == snapshot.get('input_signature') and bool(calculation)
        result = calculation.get('result') if current else None
        status = 'Selesai' if result is not None else ('Gagal / tidak layak' if current else
                 ('Input berubah' if calculation else 'Belum dihitung'))
        row = {'Skenario': case['name'], 'Disalin dari': case['source'] or '—', 'Status': status,
               'Tahun akhir': snapshot.get('base_year', 2025)+snapshot.get('planning_years', 1),
               'Model': snapshot.get('capacity_model_choice', 'Kontinu (LP)')}
        if result is not None:
            new_capacity = result.summary.get('Kapasitas tambahan kumulatif (MW)', result.summary['Kapasitas baru (MW)']).sum()
            row.update({'Biaya (juta USD/tahun)': result.annual_cost/1e6,
                        'Emisi (ribu tCO2/tahun)': result.annual_emissions/1000,
                        'Kapasitas pembangkit (MW)': result.summary['Kapasitas (MW)'].sum(),
                        'Kapasitas pembangkit baru (MW)': new_capacity})
            if getattr(result, 'npv_cost', None) is not None:
                row['Nilai kini biaya periode (juta USD)'] = result.npv_cost/1e6
            if 'Eksogen kumulatif (MW)' in result.summary:
                row['Kapasitas eksogen kumulatif (MW)'] = result.summary['Eksogen kumulatif (MW)'].sum()
                row['Kapasitas endogen kumulatif (MW)'] = result.summary['Endogen kumulatif (MW)'].sum()
        rows.append(row)
    return rows
