"""Alur periksa–terapkan XLSX, dengan penggantian input secara atomik."""
from copy import deepcopy
from hashlib import sha256

import pandas as pd
import streamlit as st

from excel_inputs import ExcelInputError, TEMPLATE_PATH, read_excel_inputs
from scenario_manager import restore, save_active


def check_upload(state, data):
    state.pop('excel_pending', None)
    state.pop('excel_notice', None)
    try:
        imported = read_excel_inputs(data)
    except ExcelInputError as exc:
        state['excel_errors'] = exc.errors
        return False
    state.pop('excel_errors', None)
    state['excel_pending'] = {'digest': sha256(data).hexdigest(), 'case_id': state['active_case'], 'inputs': imported}
    return True


def apply_upload(state, data):
    pending = state.get('excel_pending')
    if not pending or not data or pending['digest'] != sha256(data).hexdigest() or pending['case_id'] != state['active_case']:
        state['excel_errors'] = [{'Sheet': 'File', 'Baris': 0, 'Kolom': 'Unggahan',
            'Pesan': 'Periksa kembali file untuk skenario aktif sebelum menerapkan.'}]
        return False
    # Seluruh validasi selesai sebelum satu pun input model diganti.
    save_active(state)
    case_id = state['active_case']
    snapshot = deepcopy(pending['inputs'].snapshot)
    state['experiment_cases'][case_id]['snapshot'] = snapshot
    restore(state, case_id)
    state.pop('excel_pending', None)
    state.pop('excel_errors', None)
    name = state['experiment_cases'][case_id]['name']
    state['excel_notice'] = f'Input Excel diterapkan ke skenario {name}. Periksa tabel, lalu klik Jalankan Optimisasi.'
    return True


def _apply_current_file():
    uploaded = st.session_state.get('excel_upload')
    apply_upload(st.session_state, uploaded.getvalue() if uploaded is not None else None)


def render_excel_inputs():
    with st.expander('Input dari Excel — unduh template dan unggah data'):
        st.caption('Satu file untuk seluruh input satu skenario: pengaturan, pembangkit, penyimpanan, '
                   'beban puncak, profil persen, availability, dan stokastik. Baca sheet Petunjuk sebelum mengisi.')
        if TEMPLATE_PATH.is_file():
            st.download_button('Unduh Template Excel', TEMPLATE_PATH.read_bytes(), 'GENORA_template.xlsx',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', key='download_excel_template')
        else:
            st.error('Template tidak ditemukan. Sertakan folder templates beserta GENORA_template.xlsx saat menyalin aplikasi.')
        uploaded = st.file_uploader('Unggah Excel (.xlsx)', type=['xlsx'], key='excel_upload')
        if st.button('Periksa Excel', disabled=uploaded is None):
            check_upload(st.session_state, uploaded.getvalue())
        if st.session_state.get('excel_errors'):
            st.error('Input belum diterapkan. Perbaiki kesalahan berikut pada file Excel, lalu unggah dan periksa kembali.')
            st.dataframe(pd.DataFrame(st.session_state['excel_errors']), hide_index=True, width='stretch')
        pending = st.session_state.get('excel_pending')
        if pending and uploaded is not None:
            matches = pending['digest'] == sha256(uploaded.getvalue()).hexdigest() and pending['case_id'] == st.session_state['active_case']
            if matches:
                st.success('Struktur dan parameter Excel valid. Optimisasi belum dijalankan.')
                st.dataframe(pending['inputs'].summary, hide_index=True, width='stretch')
                st.caption('Terapkan akan mengganti seluruh input dan menghapus hasil optimisasi lama pada skenario aktif. '
                           'Skenario lain dan riwayat perbandingan tetap tersimpan. Validasi input belum menjamin kelayakan optimisasi.')
                st.button('Terapkan ke skenario aktif', on_click=_apply_current_file, type='primary')
            else:
                st.info('File atau skenario aktif berubah. Klik Periksa Excel kembali.')
        if st.session_state.get('excel_notice'):
            st.success(st.session_state['excel_notice'])
