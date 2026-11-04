"""Penghapusan teknologi dan input terkait pada skenario aktif."""
from model import BatteryConfig, example_inputs
from stochastic import uncertainty_catalog


def remove_technology(state, name, kind='generator'):
    tech = state['technology_inputs_v2']
    storage = state['storage_inputs']
    updates = {}
    if kind == 'generator':
        if name not in tech.Teknologi.tolist():
            raise ValueError('Teknologi pembangkit tidak ditemukan.')
        if len(tech) <= 1:
            raise ValueError('Sisakan setidaknya satu teknologi pembangkit. Tambahkan pengganti sebelum menghapus pembangkit terakhir.')
        updates['technology_inputs_v2'] = tech.loc[tech.Teknologi != name].copy().reset_index(drop=True)
        updates['profile_inputs_v2'] = state['profile_inputs_v2'].drop(columns=[name], errors='ignore').copy()
        updates['annual_availabilities'] = {year: frame.drop(columns=[name], errors='ignore').copy()
                                           for year, frame in state.get('annual_availabilities', {}).items()}
        if 'exogenous_inputs' in state:
            updates['exogenous_inputs'] = state['exogenous_inputs'].loc[state['exogenous_inputs'].Teknologi != name].copy().reset_index(drop=True)
        # Label katalog dibentuk dari data contoh agar baris input yang belum
        # lengkap sekalipun tetap dapat dihapus tanpa validasi biaya dahulu.
        reference = example_inputs()[0].iloc[[0]].copy()
        reference['Teknologi'] = name
        catalog = uncertainty_catalog(reference)
        scopes = ('generator', 'availability')
    elif kind == 'storage':
        if name not in storage.Teknologi.tolist():
            raise ValueError('Teknologi penyimpanan tambahan tidak ditemukan.')
        updates['storage_inputs'] = storage.loc[storage.Teknologi != name].copy().reset_index(drop=True)
        catalog = uncertainty_catalog(tech.iloc[:0], storages={name: BatteryConfig()})
        scopes = ('storage',)
        updates['storage_revision'] = state.get('storage_revision', 0)+1
    else:
        raise ValueError('Jenis teknologi tidak dikenal.')
    removed_parameters = {label for label, spec in catalog.items() if spec['scope'] in scopes and spec['target'] == name}
    if 'stochastic_inputs' in state:
        updates['stochastic_inputs'] = state['stochastic_inputs'].drop(columns=list(removed_parameters), errors='ignore').copy()
    if 'uncertain_parameters' in state:
        updates['uncertain_parameters'] = [label for label in state['uncertain_parameters'] if label not in removed_parameters]
    updates['input_revision_v2'] = state.get('input_revision_v2', 0)+1
    updates['stochastic_editor_revision'] = state.get('stochastic_editor_revision', -1)+1
    # Terapkan setelah pemeriksaan selesai; sumber skenario dan riwayat hasil
    # tidak dimutasi. Signature baru akan menandai hasil lama perlu dihitung ulang.
    for key, value in updates.items():
        state[key] = value
    state.pop('stochastic_layout', None)
