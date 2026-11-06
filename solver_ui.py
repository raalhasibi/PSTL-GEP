"""Pilihan solver dan pengambilan kredensial pada saat eksekusi saja."""
import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from solver_backend import SolverSettings, linprog, solver_session


LOCAL_LICENSE = 'Komputer/server (lisensi terpasang)'
WLS_LICENSE = 'Cloud (WLS)'
SERVER_CREDENTIALS = 'Secrets / environment server'
SESSION_CREDENTIALS = 'Masukkan untuk sesi ini'


def settings_for_run(state, secrets=None, environ=None):
    name = state.get('solver_choice', 'HiGHS')
    mode = 'wls' if state.get('gurobi_license_mode') == WLS_LICENSE else 'local'
    if name != 'Gurobi' or mode == 'local':
        result = SolverSettings(name=name, license_mode=mode)
    else:
        if state.get('gurobi_credential_source', SERVER_CREDENTIALS) == SESSION_CREDENTIALS:
            access = state.get('gurobi_wls_access_id', '')
            secret = state.get('gurobi_wls_secret', '')
            license_id = state.get('gurobi_wls_license_id', 0)
        else:
            credentials = (secrets or {}).get('gurobi', {})
            if credentials:
                access, secret, license_id = [credentials.get(key, '') for key in ('WLSACCESSID', 'WLSSECRET', 'LICENSEID')]
            else:
                source = os.environ if environ is None else environ
                access, secret, license_id = [source.get('GUROBI_'+key, '') for key in ('WLSACCESSID', 'WLSSECRET', 'LICENSEID')]
        if not access or not secret:
            raise ValueError('Kredensial cloud WLS belum lengkap: isi WLSACCESSID, WLSSECRET, dan LICENSEID.')
        try:
            if isinstance(license_id, bool) or float(license_id) != int(license_id):
                raise ValueError
            license_id = int(license_id)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('LICENSEID WLS harus berupa bilangan bulat positif.') from None
        result = SolverSettings(name=name, license_mode=mode, access_id='' if access is None else str(access),
                                secret='' if secret is None else str(secret), license_id=license_id)
    result.validate()
    return result


def current_solver_settings():
    secrets = {}
    if (st.session_state.get('solver_choice') == 'Gurobi'
            and st.session_state.get('gurobi_license_mode') == WLS_LICENSE
            and st.session_state.get('gurobi_credential_source', SERVER_CREDENTIALS) == SERVER_CREDENTIALS):
        try:
            secrets = {'gurobi': dict(st.secrets.get('gurobi', {}))}
        except (StreamlitSecretNotFoundError, FileNotFoundError):
            pass
    return settings_for_run(st.session_state, secrets=secrets)


def render_solver_controls():
    name = st.selectbox('Solver optimisasi', ['HiGHS', 'Gurobi'], key='solver_choice')
    mode = 'local'
    if name == 'Gurobi':
        label = st.selectbox('Lisensi Gurobi', [LOCAL_LICENSE, WLS_LICENSE], key='gurobi_license_mode')
        mode = 'wls' if label == WLS_LICENSE else 'local'
        if mode == 'local':
            st.caption('Gunakan lisensi Gurobi yang sudah terpasang pada komputer/server tempat GENORA berjalan. '
                       'Pada Streamlit Cloud, lisensi di laptop pengguna tidak otomatis tersedia di server.')
        else:
            source = st.selectbox('Sumber kredensial WLS', [SERVER_CREDENTIALS, SESSION_CREDENTIALS], key='gurobi_credential_source')
            st.caption('WLS memakai lisensi cloud dengan WLSACCESSID, WLSSECRET, dan LICENSEID. '
                       'Perhitungan tetap berjalan pada komputer/server GENORA. Gunakan lisensi yang sesuai untuk pengguna aplikasi.')
            if source == SESSION_CREDENTIALS:
                st.text_input('WLSACCESSID', type='password', key='gurobi_wls_access_id')
                st.text_input('WLSSECRET', type='password', key='gurobi_wls_secret')
                st.number_input('LICENSEID', min_value=1, value=1, step=1, key='gurobi_wls_license_id')
                st.caption('Kredensial hanya untuk sesi ini; tidak disalin ke skenario atau diekspor ke Excel/hasil.')
            else:
                st.caption('Administrator mengatur bagian [gurobi] pada Streamlit Secrets atau environment '
                           'GUROBI_WLSACCESSID, GUROBI_WLSSECRET, GUROBI_LICENSEID. Jangan unggah kredensial ke GitHub.')
        if st.button('Periksa lisensi Gurobi'):
            try:
                with solver_session(current_solver_settings()):
                    result = linprog([1.], bounds=[(0., 1.)])
                if result.success:
                    st.success('Lisensi dapat digunakan untuk uji kecil. Batas ukuran dan izin penggunaan mengikuti lisensi Anda.')
                else:
                    st.error('Uji Gurobi belum menghasilkan solusi optimal.')
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    return name, mode
