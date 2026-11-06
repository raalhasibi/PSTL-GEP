import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from model import BatteryConfig, POTENTIAL_COLUMN, add_technology, example_inputs, planning_profile, solve, validate_names
from stochastic import MAX_SCENARIOS, example_scenarios, resize_scenarios, solve_stochastic, uncertainty_catalog
from storage_inputs import STORAGE_COLUMNS, add_storage, empty_storage_table, storage_configs
from scenario_manager import initialize, save_active, switch_active, create_case, delete_active, case_overview
from multiyear import build_multiyear_problem, solve_multiyear
from year_profiles import LOAD_PERCENT, make_annual_profiles, validate_shape
from excel_ui import render_excel_inputs
from technology_management import remove_technology
from exogenous import empty_exogenous, validate_exogenous
from solver_backend import solver_session
from solver_ui import current_solver_settings, render_solver_controls

STORAGE_MODEL_LABEL = 'Blok integer + penyimpanan (MILP)'

st.set_page_config(page_title='GENORA', page_icon='⚡', layout='wide')
st.image(str(Path(__file__).resolve().parent/'assets'/'umy_electrical_engineering.png'), width=420)
st.title('⚡ GENORA')
st.markdown('**GEN**eration **O**ptimization and **R**esource **A**dequacy')
st.info('Data ilustratif • 24 jam contoh × 365 hari • Kapasitas tahun dasar + pembangunan baru • Satu node tanpa transmisi')

initialize(st.session_state)
render_excel_inputs()
with st.sidebar:
    st.header('Kelola skenario')
    cases = st.session_state['experiment_cases']
    st.selectbox('Skenario aktif', list(cases), format_func=lambda key: cases[key]['name'],
                 key='case_picker', on_change=switch_active, args=(st.session_state,))
    active_case = cases[st.session_state['active_case']]
    scenario = active_case['name']
    st.caption('Perubahan input tersimpan otomatis pada skenario aktif selama sesi ini.')
    with st.expander('Tambah skenario dari dasar atau salinan lain'):
        st.selectbox('Salin dari skenario', list(cases), format_func=lambda key: cases[key]['name'], key='case_source')
        st.text_input('Nama skenario baru', key='new_case_name', max_chars=100)
        st.button('Tambah Skenario', on_click=create_case, args=(st.session_state,))
        st.caption('Semua input disalin secara independen. Jalankan optimisasi untuk mendapatkan hasil skenario baru.')
    if st.session_state.get('case_error'):
        st.error(st.session_state['case_error'])
    st.button('Hapus skenario aktif', disabled=st.session_state['active_case'] == 'base',
              on_click=delete_active, args=(st.session_state,))
    st.caption('Skenario dasar dapat diedit dan tetap tersedia sebagai sumber salinan. '
               'Skenario eksperimen ini berbeda dari skenario probabilistik di dalam model stokastik.')

if st.session_state.pop('activate_storage_model', False):
    st.session_state['capacity_model_choice'] = STORAGE_MODEL_LABEL

with st.sidebar:
    st.header('Pengaturan Parameter Dasar')
    st.write(f'**{scenario}**')
    base_year = int(st.number_input('Tahun dasar', min_value=1900, max_value=2200, value=2025, step=1, key='base_year'))
    planning_years = int(st.number_input('Periode perencanaan (tahun)', min_value=1, max_value=50, value=1, step=1, key='planning_years'))
    target_year = base_year+planning_years
    multiyear = planning_years > 1
    growth_percent = st.number_input('Pertumbuhan beban tahunan (%)', min_value=-20., max_value=20., value=0., step=.5, key='load_growth')
    st.caption(f'Tahun akhir: {target_year}. Optimisasi kapasitas dan operasi setiap tahun dari {base_year+1} sampai {target_year}. '
               'Profil input adalah beban tahun dasar. Periode 5 tahun dari 2025 mencakup 2026–2030.')
    model_label = st.radio('Model kapasitas', ['Kontinu (LP)', 'Blok integer (MILP)', STORAGE_MODEL_LABEL], key='capacity_model_choice')
    integer = model_label != 'Kontinu (LP)'
    use_battery = model_label == STORAGE_MODEL_LABEL
    st.caption('Kontinu: penambahan kapasitas bebas. Integer: penambahan kelipatan ukuran blok; dispatch tetap kontinu.')
    solver_name, solver_license_mode = render_solver_controls()
    carbon = st.number_input('Harga karbon (USD/tCO2)', min_value=0., value=0., step=10., key='carbon_input')
    discount_rate = st.number_input('Tingkat diskonto (%)', min_value=0., max_value=100., value=8., step=1., key='discount_input')/100
    use_limit = st.checkbox('Batasi emisi tahunan', key='emissions_enabled')
    limit = st.number_input('Batas emisi (tCO2/tahun)', min_value=0., value=200000., step=10000., key='emissions_input') if use_limit else None
    stochastic = st.checkbox('Aktifkan model stokastik dua tahap', key='stochastic_enabled')
    if stochastic:
        st.caption('Kapasitas bersama untuk semua skenario; biaya minimum ekspektasian. '
                   'Beban dan batas emisi wajib dipenuhi pada SETIAP skenario.')
    st.caption('Atur profil beban dalam persen dan availability pada tabel masing-masing di halaman utama.')

tech, profiles = example_inputs()
if 'storage_inputs' not in st.session_state:
    st.session_state['storage_inputs'] = empty_storage_table()
    st.session_state['storage_revision'] = 0
if 'technology_inputs_v2' not in st.session_state:
    st.session_state['technology_inputs_v2'] = tech.copy()
    st.session_state['profile_inputs_v2'] = profiles.copy()
    st.session_state['input_revision_v2'] = 0
if 'Kapasitas tahun dasar (MW)' not in st.session_state['technology_inputs_v2']:
    st.session_state['technology_inputs_v2']['Kapasitas tahun dasar (MW)'] = 0.
    st.session_state['input_revision_v2'] += 1
if POTENTIAL_COLUMN not in st.session_state['technology_inputs_v2']:
    st.session_state['technology_inputs_v2'][POTENTIAL_COLUMN] = 0.
    st.session_state['input_revision_v2'] += 1
if 'Daya tahun dasar (MW)' not in st.session_state['storage_inputs']:
    st.session_state['storage_inputs']['Daya tahun dasar (MW)'] = 0.
    st.session_state['storage_revision'] += 1
if 'exogenous_inputs' not in st.session_state:
    st.session_state['exogenous_inputs'] = empty_exogenous()
inputs, theory = st.tabs(['1 · Input & hasil', '2 · Model matematika'])
with theory:
    st.subheader('Apa yang diputuskan model?')
    st.write('Penambahan kapasitas setiap teknologi Xᵢ (MW) dan produksi setiap jam pᵢₜ (MW). '
             'Model memilih kombinasi dengan total biaya tahunan minimum.')
    st.latex(r'K_i=K_i^0+X_i,\quad X_i\ge0')
    st.latex(r'\min\ \sum_i 1000\,[I_i\,CRF(r,L_i)X_i+F_i K_i] + \sum_{i,t}365\,(V_i + q e_i)p_{i,t}')
    st.write('Kᵢ⁰ adalah kapasitas yang sudah terpasang pada tahun dasar. Investasi historis dianggap sunk cost; '
             'hanya kapasitas baru Xᵢ dikenai investasi. O&M tetap berlaku pada seluruh kapasitas Kᵢ. '
             'Aset lama tetap tersedia; pensiun dan pelunasan investasi lama belum dimodelkan.')
    st.latex(r'CRF(r,L)=\begin{cases}\frac{r}{1-(1+r)^{-L}},&r>0\\1/L,&r=0\end{cases}')
    if stochastic:
        st.subheader('Stokastik dua tahap: keputusan kapasitas sebelum ketidakpastian diketahui')
        st.latex(r'\min\ \sum_s\pi_s\left[C_{tetap,s}(K,N_b)+C_{operasi,s}(p,c,d)\right],\qquad\sum_s\pi_s=1')
        st.write('Kapasitas pembangkit dan jumlah blok baterai sama pada semua skenario. '
                 'Variabel operasi dan energi baterai memiliki indeks skenario s. '
                 'Keseimbangan daya, batas emisi, dan siklus baterai berlaku pada setiap skenario. '
                 'Skenario mengalikan profil beban dan ketersediaan dasar.')
        st.write('Parameter ekonomi yang dipilih juga dapat berbeda antar skenario. '
                 'CRF dihitung menurut diskonto dan umur aset tiap skenario sebelum biaya dibobot probabilitas. '
                 'Jika biaya tetap sama pada semua skenario, penjumlahan berbobot menghitungnya tepat satu kali.')
        st.write('Ini model risk-neutral yang meminimalkan biaya ekspektasian. '
                 'Seluruh kondisi satu hari skenario diasumsikan diketahui saat menentukan dispatch tahap kedua '
                 '(perfect foresight dalam hari tersebut). Model belum menggunakan pohon skenario multistage, CVaR, atau chance constraints.')
    st.write('I adalah investasi awal per kW, L umur aset (tahun), r tingkat diskonto (pecahan), '
             'dan F hanya O&M tetap. Investasi awal ditampilkan terpisah; hanya investasi yang ditahunkan '
             'masuk biaya sistem tahunan. Tidak ada penghitungan investasi dua kali. '
             'Pada periode multi tahun, biaya tahunan setiap tahun didiskontokan ke tahun dasar.')
    st.subheader('Tahun dasar dan periode perencanaan')
    st.latex(r'Y_y=Y_0+y,\qquad D_{t,y}=D_{t,0}(1+g)^y,\quad y=1,\ldots,H')
    st.write('Pada mode Manual per tahun, pertumbuhan digantikan beban puncak yang diinput. '
             'Beban tiap jam = beban puncak tahun tersebut × profil persen tahun tersebut / 100. '
             'Profil beban dan availability dapat mengikuti tahun dasar atau diubah per tahun secara terpisah. '
             'Faktor stokastik diterapkan setelah profil tahunan dibentuk.')
    st.latex(r'K_{i,y}=K_i^0+\sum_{v=1}^{y}\Delta K_{i,v},\quad \Delta K_{i,y}\ge0')
    st.latex(r'K_{i,y}=K_i^0+\sum_{v=1}^{y}(X^{exo}_{i,v}+X^{endo}_{i,v})')
    st.write('X eksogen adalah pembangunan yang ditetapkan pengguna, tersedia mulai tahun operasi. '
             'X endogen dipilih solver. Eksogen tidak harus kelipatan blok; hanya endogen yang mengikuti blok integer. '
             'Investasi yang ditahunkan dan O&M eksogen ikut dihitung sejak tahun operasi, dengan biaya per teknologi yang sama. '
             'Jadwal eksogen sama pada seluruh skenario stokastik. Batas positif mencakup kapasitas dasar + eksogen + endogen.')
    st.latex(r'\min\sum_{y=1}^{H}\frac{C_{tahunan,y}}{(1+r)^y},\quad C_{investasi,y}=\sum_i1000\,I_iCRF(r,L_i)\sum_{v=1}^{y}\Delta K_{i,v}')
    st.write(f'Tahun dasar Y₀ = {base_year}, periode H = {planning_years} tahun, tahun akhir = {target_year}, '
             f'pertumbuhan beban g = {growth_percent:g}% per tahun. Bentuk profil dipertahankan. '
             'Setiap tahun memiliki keseimbangan daya, dispatch, batas emisi, dan siklus harian penyimpanan sendiri. '
             'Kapasitas baru tersedia pada tahun dibangun dan tetap tersedia pada tahun berikutnya. '
             'Batas kapasitas positif membatasi kapasitas TOTAL setiap tahun, bukan tambahan per tahun. '
             'Biaya, ukuran blok, serta batas emisi dianggap konstan antar tahun; ketersediaan mengikuti tabel availability per tahun. '
             'Investasi yang ditahunkan dikenakan pada seluruh tambahan kumulatif sejak tahun dasar; '
             'biaya operasi dan O&M juga didiskontokan pada akhir setiap tahun. Investasi awal hanya dilaporkan '
             'pada tahun penambahannya dan tidak ditambahkan lagi ke fungsi tujuan. '
             'Nilai kini ini adalah nilai kini biaya tahunan ekuivalen selama horizon, bukan arus kas CAPEX di muka. '
             'Belum ada pensiun, konstruksi tertunda, degradasi, penggantian aset, atau nilai sisa eksplisit. '
             'Umur aset dipakai untuk CRF; seluruh kapasitas diasumsikan tersedia sepanjang horizon.')
    if stochastic:
        st.write('Pada stokastik multi tahun, seluruh jadwal pembangunan ditetapkan sebelum skenario diketahui '
                 'dan sama pada semua skenario. Skenario berlaku sebagai lintasan sepanjang periode; dispatch '
                 'berbeda per tahun dan skenario. Ini model dua tahap, belum berupa pohon skenario multistage.')
    if use_battery:
        st.latex(r'\sum_i p_{i,t}+\sum_b d_{b,t}=D_t+\sum_b c_{b,t}\quad\forall t')
    else:
        st.latex(r'\sum_i p_{i,t}=D_t\quad\forall t')
    st.latex(r'0\le p_{i,t}\le a_{i,t}K_i,\qquad K_i\le K_i^{max}\ \text{hanya jika }K_i^{max}>0')
    st.write('Batas kapasitas pembangkit 0 berarti tanpa batas kapasitas. Nilai positif membatasi total kapasitas lama + baru. '
             'Ketersediaan per jam, keseimbangan daya, dan batas emisi tetap berlaku.')
    st.latex(r'K_{i,y}^0+K_{i,y}^{exo}+K_{i,y}^{endo}\le R_i\quad\text{jika potensi EBT }R_i>0')
    st.write('Potensi EBT (MW) adalah batas sumber daya per teknologi pada total kapasitas, bukan batas energi MWh/tahun. '
             'Nilai 0 berarti tanpa batas potensi. Jika batas kapasitas umum dan potensi sama-sama positif, '
             'keduanya berlaku; batas yang lebih kecil membatasi kapasitas. Isi potensi hanya pada teknologi EBT yang relevan. '
             'Ketersediaan tetap mengatur produksi per jam. Potensi tetap sama untuk seluruh tahun dan skenario stokastik.')
    if integer:
        st.latex(r'X_i=B_i N_i,\quad N_i\in\mathbb{Z}_{\ge 0},\quad N_i\le\lfloor (K_i^{max}-K_i^0)/B_i\rfloor\ \text{jika }K_i^{max}>0')
        st.write('Bᵢ adalah ukuran blok (MW), Nᵢ jumlah blok yang dibangun. Contoh: blok 50 MW '
                 'memungkinkan penambahan 0, 50, 100, 150 MW. Kapasitas lama 35 MW dan batas total 120 MW hanya mengizinkan 1 blok baru. '
                 'Jumlah blok dioptimasi langsung oleh solver terpilih, bukan pembulatan hasil LP.')
        if multiyear:
            st.latex(r'K_{i,y}=K_i^0+B_i\sum_{v=1}^{y}N_{i,v},\quad N_{i,v}\in\mathbb{Z}_{\ge0}')
    else:
        st.write('Model kontinu (LP): penambahan Xᵢ dapat bernilai pecahan, misalnya 37,5 MW.')
    st.latex(r'\sum_{i,t}365\,e_i p_{i,t}\le E^{max}\quad\text{(opsional)}')
    if use_battery:
        st.subheader('Penyimpanan: daya, energi, dan operasi')
        st.write('Persamaan berikut berlaku TERPISAH untuk setiap jenis penyimpanan b. '
                 'Biaya sistem menjumlahkan biaya seluruh jenis. Energi tidak dapat berpindah antarjenis tanpa melalui node listrik.')
        st.latex(r'N_b\in\mathbb{Z}_{\ge0},\quad \Delta P_b=B_b N_b,\quad P_b=P_b^0+\Delta P_b,\quad E_b=H_b P_b')
        st.latex(r'S_{t+1}=S_t+\eta_c c_t-d_t/\eta_d,\quad 0\le S_t\le E_b,\quad S_{24}=S_0')
        st.latex(r'0\le c_t,d_t\le P_b,\quad c_t\le Mz_t,\quad d_t\le M(1-z_t),\quad z_t\in\{0,1\}')
        st.latex(r'A_b=1000(I_P\Delta P_b+I_E H_b\Delta P_b),\quad C_b=CRF(r,L_b)A_b+1000(F_P P_b+F_E E_b)+365\sum_t V_b d_t')
        st.write('P_b⁰ adalah daya tahun dasar. Energi tahun dasar = H_b × P_b⁰; aset lama dan baru pada jenis yang sama memakai durasi dan efisiensi yang sama. '
                 'Untuk karakteristik berbeda, tambahkan sebagai jenis penyimpanan terpisah. Jumlah blok menunjukkan blok baru saja.')
        if multiyear:
            st.latex(r'P_{b,y}=P_b^0+B_b\sum_{v=1}^{y}N_{b,v},\quad E_{b,y}=H_bP_{b,y}')
            st.write('Pada model multi tahun, biaya investasi tahunan penyimpanan dikenakan pada tambahan kumulatif '
                     'daya dan energi. Kolom Jumlah blok pada hasil menunjukkan penambahan tahun tersebut; '
                     'Jumlah blok kumulatif menunjukkan seluruh pembangunan sejak tahun dasar.')
        st.write('P_b adalah daya (MW), E_b energi (MWh), H_b durasi (jam), c pengisian dan d pelepasan '
                 'di sisi node (MW). S adalah energi tersimpan di batas jam, bukan persentase. '
                 'Efisiensi isi dan keluar masing-masing akar efisiensi round-trip. '
                 'M adalah batas daya maksimum yang dapat dibangun. Biner z mencegah isi dan keluar bersamaan.')
        st.write('Energi awal dipilih model, tetapi harus kembali ke nilai yang sama pada akhir hari: '
                 'tidak ada energi awal gratis. Persamaan energi memakai langkah 1 jam, tanpa faktor 365. '
                 'Baterai dapat diisi oleh semua pembangkit. Emisi pengisiannya sudah dihitung pada pembangkit.')
        st.write('Investasi daya I_P dalam USD/kW dan investasi energi I_E dalam USD/kWh dihitung dengan umur baterai L_b. '
                 'F_P dan F_E hanya O&M tetap tahunan; V_b dalam USD/MWh energi keluar. '
                 'Gunakan komponen daya dan energi yang tidak tumpang tindih. Model belum mencakup degradasi atau self-discharge.')
    st.markdown('''- **I**: investasi awal (USD/kW); **F**: O&M tetap saja (USD/kW/tahun).
- **V**: biaya bahan bakar + biaya operasi variabel (USD/MWh).
- **q**: harga karbon (USD/tCO2); **e**: emisi operasional (tCO2/MWh).
- **D**: beban (MW); **a**: ketersediaan tiap jam (0–1).
- Setiap periode berdurasi **1 jam** dan berbobot **365** dalam perhitungan tahunan.''')
    st.warning('Satu hari contoh tidak mewakili variasi musim. Model mengabaikan unit commitment, '
               'ramping, cadangan operasi, dan gangguan paksa. '
               'Pada model blok integer, hanya jumlah blok pembangunan yang bulat; '
               'produksi per jam tetap kontinu. PLTU/PLTG dapat beroperasi dari nol sampai kapasitas tersedia. '
               'Emisi hanya emisi operasional; hasil bukan studi keandalan atau rekomendasi investasi.')
with inputs:
    st.subheader(f'Perencanaan {base_year} → {target_year} ({planning_years} tahun)')
    st.caption('Optimisasi menentukan jadwal penambahan kapasitas dan operasi untuk setiap tahun. '
               'Ubah tahun dan periode di sidebar. Kapasitas yang dibangun tersedia mulai tahun penambahannya.')
    st.subheader('Teknologi pembangkit')
    st.caption('Investasi adalah biaya awal per kW, sedangkan O&M tetap hanya biaya operasi tahunan. '
               'Semua data awal dan nilai awal formulir adalah ilustrasi untuk mengajar.')
    if st.button('Tambah Teknologi', key='show_add_technology'):
        st.session_state['adding_technology'] = not st.session_state.get('adding_technology', False)
    if st.button('Hapus Teknologi', key='show_delete_technology'):
        st.session_state['deleting_technology'] = not st.session_state.get('deleting_technology', False)
    if st.session_state.get('technology_notice'):
        st.success(st.session_state.pop('technology_notice'))
    if st.session_state.get('deleting_technology'):
        with st.form('delete_technology_form'):
            choices = [('generator', name) for name in st.session_state['technology_inputs_v2'].Teknologi]
            choices += [('storage', name) for name in st.session_state['storage_inputs'].Teknologi]
            chosen_kind, chosen_name = st.selectbox('Teknologi yang akan dihapus', choices,
                format_func=lambda item: f"{'Pembangkit' if item[0] == 'generator' else 'Penyimpanan'} · {item[1]}")
            st.caption('Penghapusan berlaku pada skenario aktif, termasuk availability per tahun dan parameter stokastik terkait. '
                       'Setidaknya satu pembangkit harus tersisa. Baterai default dapat dinonaktifkan melalui daya tahun dasar dan batas daya nol.')
            delete_submitted = st.form_submit_button('Hapus dari skenario aktif')
        if delete_submitted:
            try:
                remove_technology(st.session_state, chosen_name, chosen_kind)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state['deleting_technology'] = False
                st.session_state['technology_notice'] = f'Teknologi {chosen_name} dihapus dari skenario aktif. Klik Jalankan Optimisasi untuk menghitung ulang.'
                st.rerun()
    if st.session_state.get('adding_technology'):
        technology_kind = st.selectbox('Jenis teknologi baru', ['Pembangkit', 'Penyimpanan energi'])
        if technology_kind == 'Pembangkit':
            with st.form('add_technology_form'):
                st.write('Teknologi baru dimodelkan sebagai pembangkit dengan profil ketersediaan; '
                         'reservoir air atau rantai bahan bakar khusus belum dimodelkan.')
                new_name = st.text_input('Nama teknologi baru')
                f1, f2 = st.columns(2)
                new_investment = f1.number_input('Investasi teknologi baru (USD/kW)', min_value=0., value=1500.)
                new_om = f2.number_input('O&M tetap teknologi baru (USD/kW/tahun)', min_value=0., value=30.)
                new_variable = f1.number_input('Biaya variabel teknologi baru (USD/MWh)', min_value=0., value=10.)
                new_emissions = f2.number_input('Emisi teknologi baru (tCO2/MWh)', min_value=0., value=0.)
                new_maximum = f1.number_input('Batas kapasitas teknologi baru (MW)', min_value=0., value=0., help='0 = tanpa batas; nilai positif = batas total kapasitas lama + baru.')
                new_potential = f2.number_input('Potensi EBT teknologi baru (MW)', min_value=0., value=0., help='Batas total kapasitas EBT; 0 = tanpa batas potensi.')
                new_existing = f2.number_input('Kapasitas tahun dasar teknologi baru (MW)', min_value=0., value=0.)
                new_lifetime = f2.number_input('Umur aset teknologi baru (tahun)', min_value=1., value=25.)
                new_block = f1.number_input('Ukuran blok teknologi baru (MW)', min_value=.01, value=10.)
                new_profile = st.selectbox('Profil awal teknologi baru', ['Konstan', 'Contoh PLTS', 'Contoh PLTB'])
                new_availability = st.number_input('Ketersediaan konstan teknologi baru (0–1)', min_value=0., max_value=1., value=.9)
                st.caption('Nilai konstan dipakai hanya untuk profil Konstan. Profil awal dapat diedit per jam setelah ditambahkan. '
                           'Nama harus unik. Batas kapasitas 0 berarti tanpa batas; untuk meniadakan produksi teknologi, set ketersediaannya ke nol pada seluruh jam.')
                submitted = st.form_submit_button('Tambahkan ke model')
            if submitted:
                template = new_availability if new_profile == 'Konstan' else profiles['PLTS' if new_profile == 'Contoh PLTS' else 'PLTB'].to_numpy()
                try:
                    validate_names(st.session_state['technology_inputs_v2'].Teknologi.tolist()
                                   +st.session_state['storage_inputs'].Teknologi.tolist()+[new_name.strip()])
                    added, added_profiles = add_technology(st.session_state['technology_inputs_v2'], st.session_state['profile_inputs_v2'],
                        new_name, new_investment, new_om, new_variable, new_emissions, new_maximum, new_lifetime, new_block, template, new_existing, new_potential)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state['technology_inputs_v2'] = added
                    st.session_state['profile_inputs_v2'] = added_profiles
                    st.session_state['input_revision_v2'] += 1
                    st.session_state['adding_technology'] = False
                    st.session_state['technology_notice'] = f'Teknologi {new_name.strip()} ditambahkan. Periksa profil, lalu jalankan optimisasi.'
                    st.rerun()
        else:
            with st.form('add_storage_form'):
                st.write('Penyimpanan menyerap listrik saat diisi dan memasok listrik saat dilepas. '
                         'Model generik ini tidak mencakup hidrologi pumped hydro, degradasi, atau self-discharge. '
                         'Semua nilai awal adalah ilustrasi.')
                storage_name = st.text_input('Nama penyimpanan baru')
                s1, s2 = st.columns(2)
                sb = s1.number_input('Daya blok penyimpanan baru (MW)', min_value=.01, value=10.)
                sh = s2.number_input('Durasi penyimpanan baru (jam)', min_value=.01, value=4.)
                sm = s1.number_input('Batas daya penyimpanan baru (MW)', min_value=0., value=200.)
                sx = s2.number_input('Daya tahun dasar penyimpanan baru (MW)', min_value=0., value=0.)
                se = s2.number_input('Efisiensi penyimpanan baru (%)', min_value=1., max_value=100., value=90.)
                sip = s1.number_input('Investasi daya penyimpanan baru (USD/kW)', min_value=0., value=300.)
                sie = s2.number_input('Investasi energi penyimpanan baru (USD/kWh)', min_value=0., value=150.)
                sfp = s1.number_input('O&M daya penyimpanan baru (USD/kW/tahun)', min_value=0., value=10.)
                sfe = s2.number_input('O&M energi penyimpanan baru (USD/kWh/tahun)', min_value=0., value=2.)
                sl = s1.number_input('Umur penyimpanan baru (tahun)', min_value=1., value=15.)
                sv = s2.number_input('Biaya operasi penyimpanan baru (USD/MWh keluar)', min_value=0., value=2.)
                storage_submitted = st.form_submit_button('Tambahkan penyimpanan ke model')
            if storage_submitted:
                try:
                    config = BatteryConfig(sb, sh, sm, sfp, sfe, se/100, sv, sip, sie, sl, sx)
                    added_storage = add_storage(st.session_state['storage_inputs'], storage_name, config,
                                                st.session_state['technology_inputs_v2'].Teknologi)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state['storage_inputs'] = added_storage
                    st.session_state['storage_revision'] += 1
                    st.session_state['adding_technology'] = False
                    st.session_state['activate_storage_model'] = True
                    st.session_state['technology_notice'] = f'Penyimpanan {storage_name.strip()} ditambahkan. Mode penyimpanan diaktifkan; jalankan optimisasi.'
                    st.rerun()
    tech = st.session_state['technology_inputs_v2']
    configs = {c: st.column_config.NumberColumn(min_value=0.) for c in tech.columns[1:]}
    configs['Umur aset (tahun)'] = st.column_config.NumberColumn(min_value=1.)
    configs['Ukuran blok (MW)'] = st.column_config.NumberColumn(min_value=.01)
    configs['Batas kapasitas (MW)'] = st.column_config.NumberColumn(min_value=0., help='0 = tanpa batas kapasitas. Nilai positif = batas total kapasitas tahun dasar + kapasitas baru.')
    configs[POTENTIAL_COLUMN] = st.column_config.NumberColumn(min_value=0., help='Potensi sumber daya EBT dalam MW. Membatasi kapasitas dasar + eksogen + endogen. 0 = tanpa batas potensi.')
    technology = st.data_editor(tech, hide_index=True, disabled=['Teknologi'],
        key=f"technology_v2_{st.session_state['input_revision_v2']}", column_config=configs,
        column_order=['Teknologi', 'Kapasitas tahun dasar (MW)', POTENTIAL_COLUMN, 'Investasi (USD/kW)', 'Umur aset (tahun)', 'O&M tetap (USD/kW/tahun)',
                      'Biaya variabel (USD/MWh)', 'Emisi (tCO2/MWh)', 'Batas kapasitas (MW)', 'Ukuran blok (MW)'])
    st.session_state['technology_inputs_v2'] = technology.copy()
    block_sizes = dict(zip(technology.Teknologi, technology['Ukuran blok (MW)'])) if integer else None
    st.caption('Batas kapasitas (MW): 0 = TANPA BATAS (default). Nilai positif adalah batas TOTAL: kapasitas tahun dasar + kapasitas baru. '
               'Kapasitas tahun dasar tidak harus kelipatan blok; hanya penambahan baru yang mengikuti ukuran blok. '
               'Investasi hanya untuk kapasitas baru; O&M tetap untuk seluruh kapasitas. Nilai awal tahun dasar = 0 MW.')
    st.caption('Potensi EBT (MW): isi batas sumber daya untuk teknologi terbarukan, misalnya PLTS, PLTB, PLTA, atau PLTP. '
               'Nilai positif membatasi kapasitas total pada setiap tahun; 0 = tanpa batas potensi. '
               'Batas kapasitas umum tetap berlaku bersamaan. Jangan memperbesar potensi hanya untuk menghilangkan infeasibilitas; gunakan data sumber daya.')
    with st.expander('Penambahan kapasitas eksogen pembangkit'):
        st.caption('Tambahkan proyek yang sudah ditetapkan. Kapasitas tersedia mulai tahun operasi dan tetap tersedia '
                   'pada tahun berikutnya. Tabel kosong berarti tidak ada proyek eksogen. Beberapa baris teknologi/tahun '
                   'yang sama akan dijumlahkan. Biaya mengikuti parameter teknologi pada tabel pembangkit.')
        exogenous_inputs = st.data_editor(st.session_state['exogenous_inputs'].reset_index(drop=True), hide_index=True, num_rows='dynamic',
            key=f"exogenous_editor_{st.session_state['input_revision_v2']}",
            column_config={'Tahun operasi': st.column_config.NumberColumn(min_value=base_year+1, max_value=target_year, step=1, format='%d', required=True),
                'Teknologi': st.column_config.SelectboxColumn(options=technology.Teknologi.tolist(), required=True),
                'Tambahan eksogen (MW)': st.column_config.NumberColumn(min_value=0., required=True)})
        st.session_state['exogenous_inputs'] = exogenous_inputs.copy().reset_index(drop=True)
        st.caption('Setelah mengedit, klik Jalankan Optimisasi. Batas kapasitas 0 tetap berarti tanpa batas. '
                   'Penghapusan teknologi juga menghapus baris proyek eksogennya pada skenario aktif.')
    battery = None
    extra_storage_table = empty_storage_table()
    if use_battery:
        st.subheader('Penyimpanan energi dalam blok integer')
        st.caption('Setiap jenis dioptimasi bersama dengan pembangkit dan boleh memiliki nol blok. '
                   'Nonaktifkan baterai default dengan daya tahun dasar dan batas daya nol jika hanya ingin memakai jenis tambahan.')
        with st.expander('Parameter baterai default', expanded=True):
            b1, b2 = st.columns(2)
            block_mw = b1.number_input('Daya per blok baterai (MW)', min_value=0.01, value=10., key='bat_block')
            duration = b2.number_input('Durasi baterai (jam)', min_value=0.01, value=4., key='bat_duration')
            max_power = b1.number_input('Batas daya baterai (MW)', min_value=0., value=200., key='bat_max')
            existing_power = b2.number_input('Daya tahun dasar baterai (MW)', min_value=0., value=0., key='bat_existing')
            efficiency = b2.number_input('Efisiensi round-trip (%)', min_value=1., max_value=100., value=90., key='bat_eff')
            investment_power = b1.number_input('Investasi daya baterai (USD/kW)', min_value=0., value=300., key='bat_capex_power')
            investment_energy = b2.number_input('Investasi energi baterai (USD/kWh)', min_value=0., value=150., key='bat_capex_energy')
            battery_lifetime = b1.number_input('Umur aset baterai (tahun)', min_value=1., value=15., key='bat_lifetime')
            power_cost = b1.number_input('O&M daya baterai (USD/kW/tahun)', min_value=0., value=10., key='bat_om_power_v2')
            energy_cost = b2.number_input('O&M energi baterai (USD/kWh/tahun)', min_value=0., value=2., key='bat_om_energy_v2')
            discharge_cost = b1.number_input('Biaya operasi baterai (USD/MWh keluar)', min_value=0., value=2., key='bat_variable')
            st.caption(f'Satu blok: {block_mw:g} MW / {block_mw*duration:g} MWh. '
                       'Biaya daya dan energi dijumlahkan; gunakan komponen biaya yang tidak tumpang tindih.')
        battery = BatteryConfig(block_mw, duration, max_power, power_cost, energy_cost, efficiency/100,
                                discharge_cost, investment_power, investment_energy, battery_lifetime, existing_power)
        st.caption('Batas daya adalah batas total daya lama + baru. Energi tahun dasar = daya tahun dasar × durasi. Investasi hanya untuk blok baru.')
        if not st.session_state['storage_inputs'].empty:
            st.write('**Jenis penyimpanan tambahan**')
            storage_columns = {column: st.column_config.NumberColumn(min_value=0.) for column in STORAGE_COLUMNS}
            for column in ['Daya blok (MW)', 'Durasi (jam)', 'Umur aset (tahun)']:
                storage_columns[column] = st.column_config.NumberColumn(min_value=.01)
            storage_columns['Efisiensi round-trip (0–1)'] = st.column_config.NumberColumn(min_value=.01, max_value=1.)
            extra_storage_table = st.data_editor(st.session_state['storage_inputs'], hide_index=True, disabled=['Teknologi'],
                key=f"storage_inputs_{st.session_state['storage_revision']}", column_config=storage_columns)
            st.session_state['storage_inputs'] = extra_storage_table.copy()
            st.caption('Geser tabel untuk seluruh parameter. Batas daya nol menonaktifkan jenis tersebut. '
                       'Efisiensi pada tabel berupa pecahan, misalnya 0,90 = 90%.')
    profile = st.session_state['profile_inputs_v2'].copy()
    if 'base_load_shape' not in st.session_state:
        initial_peak = float(profile['Beban (MW)'].max())
        st.session_state['base_load_shape'] = pd.DataFrame({'Jam': profile.Jam,
            LOAD_PERCENT: profile['Beban (MW)']*100./initial_peak if initial_peak > 0 else 100.})
    revision = st.session_state['input_revision_v2']
    with st.expander('Profil beban (% terhadap beban puncak)', expanded=True):
        base_peak = st.number_input('Beban puncak tahun dasar (MW)', min_value=.001,
            value=float(profile['Beban (MW)'].max()) if float(profile['Beban (MW)'].max()) > 0 else 100., key='base_peak_mw')
        st.caption(f'Tahun dasar {base_year}: beban tiap jam = beban puncak × profil (%) / 100. '
                   'Isi 0–100%; setidaknya satu jam harus mencapai 100%. Persentase antarjam tidak dijumlahkan menjadi 100%.')
        base_shape = st.data_editor(st.session_state['base_load_shape'], hide_index=True, disabled=['Jam'],
            key=f'load_shape_editor_base_{revision}', column_config={LOAD_PERCENT: st.column_config.NumberColumn(min_value=0., max_value=100., required=True)})
        st.session_state['base_load_shape'] = base_shape.copy()
        load_shape_mode = st.selectbox('Pola beban tahun berikutnya', ['Gunakan data tahun dasar', 'Edit per tahun'], key='load_shape_mode')
        if load_shape_mode == 'Edit per tahun':
            shape_year = st.selectbox('Tahun profil beban yang diedit', list(range(base_year+1, target_year+1)))
            shapes = dict(st.session_state.get('annual_load_shapes', {}))
            selected_shape = shapes.get(shape_year, base_shape).copy()
            changed_shape = st.data_editor(selected_shape, hide_index=True, disabled=['Jam'],
                key=f'load_shape_editor_{shape_year}_{revision}', column_config={LOAD_PERCENT: st.column_config.NumberColumn(min_value=0., max_value=100., required=True)})
            shapes[shape_year] = changed_shape.copy()
            st.session_state['annual_load_shapes'] = shapes
            st.caption('Tahun yang belum memiliki profil khusus mengikuti tahun dasar. Profil khusus tersimpan per tahun; '
                       'pilih Gunakan data tahun dasar untuk mengabaikan seluruh profil khusus tanpa menghapusnya.')
    with st.expander('Availability setiap teknologi pembangkit', expanded=True):
        st.caption(f'Availability tahun dasar {base_year} dalam pecahan 0–1. Nilai 0,5 berarti '
                   'maksimum produksi pada jam tersebut 50% dari kapasitas tersedia.')
        availability_config = {name: st.column_config.NumberColumn(min_value=0., max_value=1., required=True) for name in technology.Teknologi}
        base_availability = st.data_editor(profile[['Jam']+technology.Teknologi.tolist()], hide_index=True, disabled=['Jam'],
            key=f'availability_editor_base_{revision}', column_config=availability_config)
        availability_mode = st.selectbox('Availability tahun berikutnya', ['Gunakan data tahun dasar', 'Edit per tahun'], key='availability_mode')
        if availability_mode == 'Edit per tahun':
            availability_year = st.selectbox('Tahun availability yang diedit', list(range(base_year+1, target_year+1)))
            availabilities = dict(st.session_state.get('annual_availabilities', {}))
            selected_availability = availabilities.get(availability_year, base_availability).copy()
            for name in technology.Teknologi:
                if name not in selected_availability:
                    selected_availability[name] = base_availability[name].to_numpy()
            changed_availability = st.data_editor(selected_availability[['Jam']+technology.Teknologi.tolist()], hide_index=True, disabled=['Jam'],
                key=f'availability_editor_{availability_year}_{revision}', column_config=availability_config)
            availabilities[availability_year] = changed_availability.copy()
            st.session_state['annual_availabilities'] = availabilities
            st.caption('Tahun tanpa data khusus mengikuti availability tahun dasar. Teknologi baru mewarisi '
                       'nilai tahun dasar sampai datanya diubah. Pilihan ini terpisah dari pola beban.')
    profile['Beban (MW)'] = base_shape[LOAD_PERCENT].to_numpy(dtype=float)*base_peak/100.
    for name in technology.Teknologi:
        profile[name] = base_availability[name].to_numpy(dtype=float)
    st.session_state['profile_inputs_v2'] = profile.copy()
    annual_load_factors = None
    annual_profiles = None
    forecast_error = None
    with st.expander('Proyeksi beban selama periode perencanaan'):
        projection_mode = st.selectbox('Metode proyeksi beban', ['Pertumbuhan tahunan', 'Manual per tahun'], key='load_projection_mode')
        manual_forecast = None
        if projection_mode == 'Manual per tahun':
            years = list(range(base_year+1, target_year+1))
            manual_values = dict(st.session_state.get('manual_forecast_inputs', {}))
            for year in years:
                manual_values.setdefault(year, float(profile['Beban (MW)'].max())*(1.+growth_percent/100.)**(year-base_year))
            layout = tuple(years)
            if st.session_state.get('manual_forecast_layout') != layout:
                st.session_state['manual_forecast_layout'] = layout
                st.session_state['manual_forecast_revision'] = st.session_state.get('manual_forecast_revision', -1)+1
            if st.button('Isi ulang dari pertumbuhan tahunan'):
                manual_values.update({year: float(profile['Beban (MW)'].max())*(1.+growth_percent/100.)**(year-base_year) for year in years})
                st.session_state['manual_forecast_revision'] += 1
            manual_key = f"manual_forecast_editor_{st.session_state['manual_forecast_revision']}"
            st.session_state['manual_forecast_editor_key'] = manual_key
            st.caption(f'Edit beban puncak setiap tahun. Tahun dasar {base_year} mengikuti tabel jam. '
                       'Pertumbuhan tahunan tidak dipakai dalam mode manual, kecuali untuk mengisi nilai awal atau tombol isi ulang.')
            manual_forecast = st.data_editor(pd.DataFrame({'Tahun': years, 'Puncak beban (MW)': [manual_values[y] for y in years]}),
                hide_index=True, disabled=['Tahun'], num_rows='fixed', key=manual_key,
                column_config={'Puncak beban (MW)': st.column_config.NumberColumn(min_value=.001, required=True)})
            manual_values.update(dict(zip(years, manual_forecast['Puncak beban (MW)'])))
            st.session_state['manual_forecast_inputs'] = manual_values
        try:
            validate_shape(base_shape, profile.Jam)
            projected_profile = planning_profile(profile, base_year, planning_years, growth_percent/100.)
            if manual_forecast is not None:
                peaks = pd.to_numeric(manual_forecast['Puncak beban (MW)'], errors='coerce')
                if peaks.isna().any() or not peaks.map(lambda value: 0 < value < float('inf')).all():
                    raise ValueError('Beban puncak manual harus berupa angka hingga dan lebih besar dari nol pada setiap tahun.')
                annual_load_factors = {int(year): float(value)/float(profile['Beban (MW)'].max())
                    for year, value in zip(manual_forecast['Tahun'], peaks)}
            peaks_by_year = {year: base_peak*(annual_load_factors[year] if annual_load_factors is not None else (1.+growth_percent/100.)**(year-base_year))
                for year in range(base_year+1, target_year+1)}
            annual_profiles = make_annual_profiles(profile, base_shape, peaks_by_year,
                st.session_state.get('annual_load_shapes', {}) if load_shape_mode == 'Edit per tahun' else None,
                st.session_state.get('annual_availabilities', {}) if availability_mode == 'Edit per tahun' else None)
            forecast_rows = []
            for elapsed in range(planning_years+1):
                year_profile = profile if elapsed == 0 else annual_profiles[base_year+elapsed]
                forecast_rows.append({'Tahun': base_year+elapsed,
                    'Puncak beban (MW)': float(year_profile['Beban (MW)'].max()),
                    'Energi beban (MWh/tahun)': float(year_profile['Beban (MW)'].sum())*365})
            forecast = pd.DataFrame(forecast_rows)
        except (ValueError, TypeError) as exc:
            forecast_error = str(exc)
            st.error(str(exc))
        else:
            st.dataframe(forecast.round(2), hide_index=True, width='stretch')
            st.caption('Tabel ini adalah proyeksi beban. Optimisasi mencakup setiap tahun setelah tahun dasar. '
                       'Energi tahunan dihitung mengikuti profil persen untuk tahun tersebut; tidak diedit secara terpisah. '
                       'Pada model stokastik, nilai ini belum dikalikan faktor masing-masing skenario. '
                       'Setelah mengedit, klik Jalankan Optimisasi.')
    scenario_table = None
    if stochastic:
        st.subheader('Skenario ketidakpastian')
        st.caption('Pilih parameter yang tidak pasti, lalu tentukan jumlah skenario. '
                   'Probabilitas berlaku untuk gabungan nilai pada satu baris skenario, bukan probabilitas independen tiap parameter. '
                   'Parameter yang tidak dipilih memakai nilai dasar meskipun memiliki nilai tersimpan dari sebelumnya.')
        catalog = uncertainty_catalog(technology, carbon_price=carbon, discount_rate=discount_rate, emissions_limit=limit,
                                      battery=battery, storages=storage_configs(extra_storage_table, validate=False))
        defaults = ['Faktor beban']+[f'Faktor {name}' for name in technology.Teknologi if name in ('PLTS', 'PLTB')]
        if 'uncertain_parameters' in st.session_state:
            existing_selection = st.session_state['uncertain_parameters']
            retained = [label for label in existing_selection if label in catalog]
            if retained != existing_selection:
                st.session_state['uncertain_parameters'] = retained
        selected_parameters = st.multiselect('Parameter yang tidak pasti', list(catalog), default=defaults, key='uncertain_parameters')
        scenario_count = int(st.number_input('Jumlah skenario ketidakpastian', min_value=2, max_value=MAX_SCENARIOS,
                                             value=3, step=1, key='stochastic_count'))
        scenario_base = st.session_state.get('stochastic_inputs', example_scenarios(technology.Teknologi))
        scenario_base, resized = resize_scenarios(scenario_base, scenario_count, catalog)
        layout = (st.session_state['input_revision_v2'], scenario_count, tuple(selected_parameters))
        previous_layout = st.session_state.get('stochastic_layout')
        if previous_layout != layout:
            st.session_state['stochastic_editor_revision'] = st.session_state.get('stochastic_editor_revision', -1)+1
            st.session_state['stochastic_layout'] = layout
        if resized:
            st.info('Jumlah skenario berubah: nilai baris lama dipertahankan dan probabilitas disetel merata. '
                    'Periksa serta sesuaikan kembali probabilitasnya.')
        if st.button('Samakan probabilitas skenario'):
            scenario_base['Probabilitas'] = 1/scenario_count
            st.session_state['stochastic_editor_revision'] += 1
        columns = ['Skenario', 'Probabilitas']+selected_parameters
        scenario_config = {'Probabilitas': st.column_config.NumberColumn(min_value=0., max_value=1.)}
        for label in selected_parameters:
            spec = catalog[label]
            scenario_config[label] = st.column_config.NumberColumn(min_value=.000001 if spec['positive'] else 0.,
                                                                  max_value=spec['maximum'])
        editor_key = f"stochastic_inputs_{st.session_state['stochastic_editor_revision']}"
        st.session_state['stochastic_editor_key'] = editor_key
        scenario_table = st.data_editor(scenario_base[columns], hide_index=True, num_rows='fixed',
                                       key=editor_key, column_config=scenario_config)
        for column in columns:
            scenario_base[column] = scenario_table[column].to_numpy()
        st.session_state['stochastic_inputs'] = scenario_base.copy()
        st.caption(f"Total probabilitas: {pd.to_numeric(scenario_table['Probabilitas'], errors='coerce').sum():.6f}")
        st.caption('Kolom Faktor adalah pengali profil dasar; ketersediaan hasil perkalian dibatasi maksimum 1. '
                   'Kolom selain Faktor adalah nilai aktual sesuai satuan judul, bukan pengali. '
                   'Ukuran blok, batas pembangunan, dan durasi penyimpanan tetap sebagai desain tahap pertama. '
                   'Data dan probabilitas awal hanya ilustrasi pembelajaran.')
        if not selected_parameters:
            st.info('Tidak ada parameter tidak pasti yang dipilih; semua skenario memakai nilai dasar yang sama.')
        with st.expander('Nilai dasar parameter yang dipilih'):
            st.dataframe(pd.DataFrame([{'Parameter': label, 'Nilai dasar': catalog[label]['base'],
                                       'Cara pengisian': 'Pengali profil dasar' if catalog[label]['factor'] else 'Nilai aktual sesuai satuan'}
                                      for label in selected_parameters], columns=['Parameter', 'Nilai dasar', 'Cara pengisian']), hide_index=True)
    # Hasil hanya berlaku untuk input yang dihitung, bukan input yang baru diedit.
    signature = json.dumps({
        'solver': solver_name, 'solver_license_mode': solver_license_mode,
        'planning_semantics': 'joint_multiyear_annualized_npv_v1',
        'capacity_limit_semantics': 'zero_is_unlimited',
        'scenario': scenario, 'model': model_label, 'carbon': carbon, 'limit': limit, 'discount_rate': discount_rate,
        'base_year': base_year, 'planning_years': planning_years, 'growth_percent': growth_percent,
        'load_projection_mode': projection_mode,
        'manual_forecast': manual_forecast.to_json(orient='split', double_precision=15) if manual_forecast is not None else None,
        'load_shape_mode': load_shape_mode, 'availability_mode': availability_mode,
        'annual_profiles': {str(year): frame.to_json(orient='split', double_precision=15) for year, frame in (annual_profiles or {}).items()},
        'technology': technology.to_json(orient='split', double_precision=15),
        'exogenous_additions': exogenous_inputs.to_json(orient='split', double_precision=15),
        'profile': profile.to_json(orient='split', double_precision=15),
        'blocks': block_sizes, 'battery': vars(battery) if battery else None,
        'storages': extra_storage_table.to_json(orient='split', double_precision=15),
        'stochastic': stochastic,
        'uncertainty_scenarios': scenario_table.to_json(orient='split', double_precision=15) if stochastic else None,
        'uncertainty_parameters': selected_parameters if stochastic else [],
    }, sort_keys=True)
    st.session_state['input_signature'] = signature
    st.caption('Selesaikan perubahan input (Enter atau klik sel lain), lalu tekan tombol di bawah. '
               'Optimisasi hanya dijalankan ketika tombol ditekan.')
    if st.button('Jalankan Optimisasi', type='primary', key='run_optimization'):
        with st.spinner('Menjalankan optimisasi...'):
            try:
                if forecast_error:
                    raise ValueError(forecast_error)
                validated_exogenous = validate_exogenous(exogenous_inputs, technology, base_year, planning_years)
                options = dict(carbon_price=carbon, emissions_limit=limit,
                               capacity_model='integer' if integer else 'continuous',
                               block_sizes=block_sizes, battery=battery, discount_rate=discount_rate,
                               storages=storage_configs(extra_storage_table))
                with solver_session(current_solver_settings()):
                    if multiyear or not validated_exogenous.empty:
                        horizon = dict(base_year=base_year, planning_years=planning_years, annual_growth=growth_percent/100., annual_profiles=annual_profiles,
                                       exogenous_additions=validated_exogenous)
                        computed = solve_stochastic(technology, profile, scenario_table, uncertainty_parameters=selected_parameters,
                            problem_builder=build_multiyear_problem, **horizon, **options) if stochastic else solve_multiyear(technology, profile, **horizon, **options)
                    else:
                        projected_profile = annual_profiles[target_year]
                        computed = solve_stochastic(technology, projected_profile, scenario_table, uncertainty_parameters=selected_parameters,
                                                     **options) if stochastic else solve(technology, projected_profile, **options)
                st.session_state['optimization'] = {'signature': signature, 'result': computed,
                    'planning': {'Tahun dasar': base_year, 'Periode perencanaan (tahun)': planning_years,
                                 'Tahun akhir': target_year, 'Pertumbuhan beban tahunan (%)': growth_percent,
                                 'Metode proyeksi beban': projection_mode,
                                 'Solver': solver_name, 'Mode lisensi Gurobi': solver_license_mode if solver_name == 'Gurobi' else '—',
                                 'Pola beban tahun berikutnya': load_shape_mode,
                                 'Availability tahun berikutnya': availability_mode}}
            except (ValueError, RuntimeError) as exc:
                st.session_state['optimization'] = {'signature': signature, 'error': str(exc),
                                                    'diagnosis': getattr(exc, 'diagnosis', None),
                                                    'scenario_diagnoses': getattr(exc, 'scenario_diagnoses', None)}
    calculation = st.session_state.get('optimization')
    result = None
    if calculation is None:
        st.info('Atur input, lalu klik Jalankan Optimisasi untuk melihat hasil.')
    elif calculation['signature'] != signature:
        st.warning('Input berubah. Klik Jalankan Optimisasi untuk menghitung ulang. '
                   'Hasil sebelumnya disembunyikan agar tidak tertukar dengan input baru.')
    elif 'error' in calculation:
        st.error(calculation['error'])
        diagnosis = calculation.get('diagnosis')
        failures = calculation.get('scenario_diagnoses')
        if failures:
            selected_failure = st.selectbox('Skenario untuk diagnosis', list(failures))
            diagnosis = failures[selected_failure]
            st.warning('Diagnosis dan saran di bawah hanya berlaku untuk skenario terpilih. '
                       'Perbaikan tersebut belum menjamin seluruh skenario stokastik layak; '
                       'periksa semua skenario bermasalah dan jalankan optimisasi kembali. '
                       'Jika parameter dipilih sebagai tidak pasti, ubah nilainya pada baris skenario terkait; '
                       'mengubah nilai dasar tidak mengganti nilai skenario.')
        if diagnosis:
            st.subheader('Diagnosis infeasibilitas')
            for finding in diagnosis['findings']:
                st.write('• ' + finding)
            if diagnosis['suggestions']:
                st.subheader('Saran perubahan parameter — teruji layak')
                st.caption('Setiap baris adalah alternatif perubahan SATU parameter dari input saat ini. '
                           'Contoh nilai ini bukan perubahan minimum atau rekomendasi biaya termurah. '
                           'Terapkan secara manual, lalu klik Jalankan Optimisasi kembali.')
                suggestions = pd.DataFrame(diagnosis['suggestions'])
                st.dataframe(suggestions, hide_index=True, width='stretch')
                st.download_button('Unduh saran diagnosis CSV', suggestions.to_csv(index=False).encode('utf-8-sig'),
                                   'saran_diagnosis.csv', 'text/csv')
            with st.expander('Kekurangan pasokan per jam', expanded=True):
                st.caption('Slack beban hanya untuk diagnosis, bukan solusi operasi yang memenuhi seluruh beban. '
                           'Batas daya baterai belum menjamin tersedianya energi. '
                           'Kekurangan pada solusi diagnosis juga dapat disebabkan batas emisi.')
                st.dataframe(diagnosis['hourly'].round(3), hide_index=True, width='stretch')
            with st.expander('Batas kapasitas efektif setelah pembulatan blok'):
                st.dataframe(diagnosis['capacity'].round(3), hide_index=True, width='stretch')
    else:
        result = calculation['result']
        st.success('Optimisasi selesai. Hasil sesuai dengan input saat ini.')
    if result is not None:
        plan_result = result
        has_plan = bool(getattr(plan_result, 'year_results', {}))
        display_year = target_year
        st.subheader(f'Hasil · {scenario} · {base_year+1}–{target_year}')
        if getattr(plan_result, 'year_results', {}):
            st.write(f'**Nilai kini biaya tahunan ekuivalen seluruh periode: {plan_result.npv_cost/1e6:,.2f} juta USD**')
            st.caption('Fungsi tujuan menjumlahkan biaya tahunan yang didiskontokan ke tahun dasar. '
                       'Investasi tahunan (CRF) dikenakan pada kapasitas tambahan kumulatif. '
                       'Investasi awal dilaporkan terpisah sebagai kebutuhan pembangunan, tanpa dihitung dua kali.')
            st.dataframe(plan_result.annual_metrics.round(3), hide_index=True, width='stretch')
            st.subheader('Rencana pembangunan pembangkit per tahun')
            plan_cols = ['Tahun', 'Teknologi', 'Kapasitas awal tahun (MW)', 'Kapasitas eksogen (MW)', 'Kapasitas endogen (MW)', 'Kapasitas baru (MW)', 'Kapasitas (MW)', 'Investasi awal (USD)']
            if 'Jumlah blok' in plan_result.capacity_plan:
                plan_cols += ['Jumlah blok']
            st.dataframe(plan_result.capacity_plan[plan_cols].round(3), hide_index=True, width='stretch')
            st.plotly_chart(px.bar(plan_result.capacity_plan, x='Tahun', y='Kapasitas baru (MW)', color='Teknologi',
                title='Penambahan pembangkit setiap tahun'), width='stretch')
            addition_types = plan_result.capacity_plan.melt(id_vars=['Tahun', 'Teknologi'],
                value_vars=['Kapasitas eksogen (MW)', 'Kapasitas endogen (MW)'], var_name='Sumber penambahan', value_name='Tambahan (MW)')
            st.plotly_chart(px.bar(addition_types, x='Tahun', y='Tambahan (MW)', color='Sumber penambahan',
                title='Penambahan eksogen dan hasil optimisasi'), width='stretch')
            capacity_by_year = px.bar(plan_result.capacity_plan, x='Tahun', y='Kapasitas (MW)', color='Teknologi',
                barmode='stack', title='Kapasitas pembangkit tersedia setiap tahun')
            capacity_by_year.update_xaxes(type='category')
            st.plotly_chart(capacity_by_year, width='stretch')
            st.download_button('Unduh rencana pembangkit CSV', plan_result.capacity_plan.to_csv(index=False).encode('utf-8-sig'), 'rencana_pembangkit.csv', 'text/csv')
            st.download_button('Unduh biaya dan emisi tahunan CSV', plan_result.annual_metrics.to_csv(index=False).encode('utf-8-sig'), 'hasil_tahunan.csv', 'text/csv')
            if not plan_result.storage_plan.empty:
                st.subheader('Rencana pembangunan penyimpanan per tahun')
                st.dataframe(plan_result.storage_plan[['Tahun', 'Teknologi', 'Daya awal tahun (MW)', 'Daya baru (MW)', 'Daya (MW)',
                    'Energi baru (MWh)', 'Energi (MWh)', 'Jumlah blok', 'Investasi awal (USD)']].round(3), hide_index=True, width='stretch')
                st.download_button('Unduh rencana penyimpanan CSV', plan_result.storage_plan.to_csv(index=False).encode('utf-8-sig'), 'rencana_penyimpanan.csv', 'text/csv')
            all_year_dispatch = []
            for year, yr in plan_result.year_results.items():
                if stochastic:
                    all_year_dispatch.extend(sr.dispatch.assign(Tahun=year, Skenario=name) for name, sr in yr.scenario_results.items())
                else:
                    all_year_dispatch.append(yr.dispatch.assign(Tahun=year))
            st.download_button('Unduh dispatch seluruh tahun CSV', pd.concat(all_year_dispatch, ignore_index=True).to_csv(index=False).encode('utf-8-sig'), 'dispatch_seluruh_tahun.csv', 'text/csv')
            display_year = st.selectbox('Tahun untuk rincian hasil dan dispatch', list(plan_result.year_results), index=len(plan_result.year_results)-1)
            result = plan_result.year_results[display_year]
        st.subheader(f'Rincian tahun {display_year}')
        st.caption(f'Model: {model_label} · Solver: {solver_name} · Tahun dasar {base_year} · Periode {planning_years} tahun')
        st.info(f'Kapasitas, operasi, biaya tahunan, dan emisi berikut adalah untuk tahun {display_year}. '
                'Kapasitas baru mencakup eksogen + endogen tahun ini. Jumlah blok menunjukkan blok endogen baru; '
                'kapasitas total mencakup pembangunan sebelumnya.')
        planning_metadata = pd.DataFrame([calculation['planning']])
        st.download_button('Unduh pengaturan perencanaan CSV', planning_metadata.to_csv(index=False).encode('utf-8-sig'),
                           'pengaturan_perencanaan.csv', 'text/csv')
        st.download_button('Unduh proyeksi beban CSV', forecast.to_csv(index=False).encode('utf-8-sig'),
                           'proyeksi_beban.csv', 'text/csv')
        profile_export = pd.concat([frame.assign(Tahun=year, **{LOAD_PERCENT: frame['Beban (MW)']/float(frame['Beban (MW)'].max())*100.})
            for year, frame in {base_year: profile, **annual_profiles}.items()], ignore_index=True)
        st.download_button('Unduh profil beban dan availability seluruh tahun CSV', profile_export.to_csv(index=False).encode('utf-8-sig'),
                           'profil_tahunan.csv', 'text/csv')
        display_dispatch = result.dispatch
        display_storage = result.storage_dispatch
        if stochastic:
            st.info('Hasil utama adalah nilai ekspektasian berbobot probabilitas. Kapasitas investasi sama untuk semua skenario. '
                    'Batas emisi diberlakukan per skenario, bukan hanya pada nilai ekspektasi.')
            st.dataframe(result.scenario_metrics.round(2), hide_index=True, width='stretch')
            selected_dispatch = st.selectbox('Skenario untuk grafik dispatch', list(result.scenario_results))
            display_dispatch = result.scenario_results[selected_dispatch].dispatch
            display_storage = result.scenario_results[selected_dispatch].storage_dispatch
            st.caption(f'Grafik dispatch dan energi baterai: skenario {selected_dispatch}. '
                       'Tabel produksi, biaya, dan throughput baterai di bawah adalah ekspektasi.')
            with st.expander('Nilai parameter pada skenario grafik'):
                st.dataframe(result.scenario_inputs[result.scenario_inputs.Skenario == selected_dispatch], hide_index=True, width='stretch')
            all_dispatch = pd.concat([r.dispatch.assign(Skenario=name, Tahun=display_year) for name, r in result.scenario_results.items()], ignore_index=True)
            st.download_button('Unduh seluruh dispatch skenario CSV', all_dispatch.to_csv(index=False).encode('utf-8-sig'),
                               'dispatch_semua_skenario.csv', 'text/csv')
            st.download_button('Unduh ringkasan skenario CSV', result.scenario_metrics.to_csv(index=False).encode('utf-8-sig'),
                               'ringkasan_skenario.csv', 'text/csv')
            st.download_button('Unduh input skenario CSV', result.scenario_inputs.to_csv(index=False).encode('utf-8-sig'),
                               'input_skenario.csv', 'text/csv')
        a, b, c = st.columns(3)
        a.metric('Ekspektasi biaya sistem' if stochastic else 'Biaya sistem termasuk karbon', f'{result.annual_cost/1e6:,.2f} juta USD/tahun')
        b.metric('Biaya / energi ekspektasian' if stochastic else 'Biaya rata-rata sistem', f'{result.annual_cost/result.annual_energy:,.2f} USD/MWh')
        c.metric('Ekspektasi emisi' if stochastic else 'Emisi operasional', f'{result.annual_emissions/1000:,.1f} ribu tCO2/tahun')
        st.caption('Biaya rata-rata = total biaya tahunan ÷ energi yang dilayani; bukan tarif listrik atau LCOE per teknologi.')
        total_investment = result.summary['Investasi awal (USD)'].sum()
        annual_investment = result.summary['Investasi tahunan (USD/tahun)'].sum()
        if use_battery:
            total_investment += result.battery_summary['Investasi awal (USD)'].sum()
            annual_investment += result.battery_summary['Investasi tahunan (USD/tahun)'].sum()
        investment_label = 'Ekspektasi investasi kapasitas baru' if stochastic else 'Investasi kapasitas baru'
        st.write(f'**{investment_label}: {total_investment/1e6:,.2f} juta USD** · '
                 f'Investasi yang ditahunkan: {annual_investment/1e6:,.2f} juta USD/tahun · Diskonto {discount_rate:.1%}')
        st.caption('Biaya tetap pada tabel hasil = investasi tahunan + O&M tetap. '
                   'Kolom rincian investasi dan O&M bukan biaya tambahan di luar biaya tetap tersebut.')
        left, right = st.columns(2)
        added_column = 'Kapasitas tambahan kumulatif (MW)' if has_plan else 'Kapasitas baru (MW)'
        capacity_table = result.summary[['Teknologi', 'Kapasitas tahun dasar (MW)', added_column]].copy()
        if use_battery:
            for _, row in result.storage_summary.iterrows():
                capacity_table.loc[len(capacity_table)] = [row['Teknologi'], row['Daya tahun dasar (MW)'], row['Daya tambahan kumulatif (MW)'] if has_plan else row['Daya baru (MW)']]
        capacity_table = capacity_table.melt(id_vars='Teknologi', var_name='Komponen', value_name='Kapasitas (MW)')
        left.plotly_chart(px.bar(capacity_table, x='Teknologi', y='Kapasitas (MW)', color='Komponen',
                                 title='Kapasitas tahun dasar dan penambahan optimal'), width='stretch')
        fig = go.Figure()
        for name in tech.Teknologi:
            fig.add_scatter(x=display_dispatch.Jam, y=display_dispatch[name], name=name, stackgroup='one')
        if use_battery:
            for name, operation in display_storage.items():
                fig.add_scatter(x=operation.Jam, y=operation['Keluar baterai (MW)'], name=f'{name} keluar', stackgroup='one')
                fig.add_scatter(x=operation.Jam, y=-operation['Isi baterai (MW)'],
                               name=f'{name} isi', stackgroup='charging')
        fig.add_scatter(x=display_dispatch.Jam, y=display_dispatch['Beban (MW)'], name='Beban',
                       line=dict(color='black', dash='dash'))
        fig.update_layout(title='Operasi pembangkit', xaxis_title='Jam', yaxis_title='MW')
        if use_battery:
            fig.add_hline(y=0, line_color='gray', line_width=1)
        right.plotly_chart(fig, width='stretch')
        if use_battery:
            st.caption('Grafik dispatch: pengisian setiap penyimpanan negatif, pelepasan positif. '
                       'Total pembangkitan + pelepasan − pengisian = beban. '
                       'Area pengisian ditumpuk terpisah di bawah nol.')
        st.dataframe(result.summary.round(2), hide_index=True, width='stretch')
        st.download_button('Unduh ringkasan CSV', result.summary.assign(**{'Tahun dasar': base_year, 'Tahun hasil': display_year, 'Tahun akhir': target_year}).to_csv(index=False).encode('utf-8-sig'), 'ringkasan.csv', 'text/csv')
        st.download_button('Unduh dispatch CSV', display_dispatch.assign(Tahun=display_year).to_csv(index=False).encode('utf-8-sig'), 'dispatch.csv', 'text/csv')
        if use_battery:
            st.subheader('Kapasitas & operasi penyimpanan')
            ba, bb, bc = st.columns(3)
            ba.metric('Jumlah blok baru penyimpanan', f"{int(result.storage_summary['Jumlah blok'].sum())}")
            bb.metric('Total daya penyimpanan', f"{result.storage_summary['Daya (MW)'].sum():,.1f} MW")
            bc.metric('Total energi penyimpanan', f"{result.storage_summary['Energi (MWh)'].sum():,.1f} MWh")
            if result.storage_summary['Jumlah blok'].sum() == 0:
                st.info('Tidak diperlukan blok penyimpanan baru pada tahun ini; nol blok baru adalah solusi yang valid. Kapasitas tahun dasar dan pembangunan tahun sebelumnya tetap tersedia.')
            st.caption('Biaya sistem sudah termasuk seluruh penyimpanan. Produksi pembangkit adalah energi bruto, '
                       'termasuk pengisian. Energi keluar penyimpanan bukan pembangkitan primer baru. '
                       'Tiap jenis memiliki batas daya dan energi sendiri; kapasitas antarjenis tidak saling dipinjam.')
            st.dataframe(result.storage_summary.round(2), hide_index=True, width='stretch')
            selected_storage = st.selectbox('Penyimpanan untuk grafik energi', list(display_storage))
            bs = result.storage_summary.set_index('Teknologi').loc[selected_storage]
            operation = display_storage[selected_storage]
            levels = [operation['Energi awal jam (MWh)'].iloc[0]] + operation['Energi akhir jam (MWh)'].tolist()
            energy_fig = go.Figure(go.Scatter(x=list(range(len(levels))), y=levels, mode='lines+markers', name='Energi tersimpan'))
            energy_fig.add_hline(y=float(bs['Energi (MWh)']), line_dash='dash', annotation_text='Kapasitas energi')
            energy_fig.update_layout(title=f'Energi {selected_storage} pada batas jam (S₀ = S₂₄)', xaxis_title='Batas jam', yaxis_title='MWh')
            st.plotly_chart(energy_fig, width='stretch')
            operation_chart = operation.rename(columns={'Isi baterai (MW)': 'Pengisian (MW)', 'Keluar baterai (MW)': 'Pelepasan (MW)'})
            st.plotly_chart(px.line(operation_chart, x='Jam', y=['Pengisian (MW)', 'Pelepasan (MW)'],
                                    title=f'Operasi {selected_storage}', labels={'value': 'MW', 'variable': 'Operasi'}), width='stretch')
            st.download_button('Unduh ringkasan penyimpanan CSV', result.storage_summary.to_csv(index=False).encode('utf-8-sig'),
                               'penyimpanan.csv', 'text/csv')
        if st.button('Simpan hasil untuk perbandingan'):
            comparison_investment = total_investment
            if has_plan:
                comparison_investment = plan_result.capacity_plan['Investasi awal (USD)'].sum()
                if not plan_result.storage_plan.empty:
                    comparison_investment += plan_result.storage_plan['Investasi awal (USD)'].sum()
            saved = st.session_state.setdefault('saved', [])
            saved.append({'Skenario': scenario, 'Model': model_label,
                          'Solver': solver_name, 'Mode lisensi Gurobi': solver_license_mode if solver_name == 'Gurobi' else '—',
                          'Tahun dasar': base_year, 'Periode perencanaan (tahun)': planning_years,
                          'Tahun akhir': target_year, 'Pertumbuhan beban tahunan (%)': growth_percent,
                          'Pendekatan': 'Stokastik dua tahap' if stochastic else 'Deterministik',
                          'Skenario ketidakpastian': scenario_table.to_json(orient='records') if stochastic else '—',
                          'Parameter tidak pasti': ', '.join(selected_parameters) if stochastic else '—',
                          'Ukuran blok (MW)': str(block_sizes) if integer else '—',
                          'Biaya (juta USD/tahun)': plan_result.annual_cost/1e6,
                          'Emisi (ribu tCO2/tahun)': plan_result.annual_emissions/1000,
                          'Nilai kini biaya periode (juta USD)': plan_result.npv_cost/1e6 if has_plan else None,
                          'Diskonto (%)': discount_rate*100,
                          'Investasi awal (juta USD)': comparison_investment/1e6,
                          'Investasi tahunan (juta USD/tahun)': (plan_result.summary['Investasi tahunan (USD/tahun)'].sum()+
                            (plan_result.storage_summary['Investasi tahunan (USD/tahun)'].sum() if use_battery else 0.))/1e6,
                          'Penyimpanan (MW)': plan_result.storage_summary['Daya (MW)'].sum() if use_battery else 0.,
                          'Penyimpanan (MWh)': plan_result.storage_summary['Energi (MWh)'].sum() if use_battery else 0.,
                          'Parameter baterai': str(vars(battery)) if use_battery else '—',
                          'Parameter penyimpanan': extra_storage_table.to_json(orient='records') if use_battery else '—',
                          'Penyimpanan per teknologi': plan_result.storage_summary.to_json(orient='records') if use_battery else '—',
                          **dict(zip(plan_result.summary.Teknologi, plan_result.summary['Kapasitas (MW)']))})
    if st.session_state.get('saved'):
        st.subheader('Perbandingan hasil tersimpan')
        st.caption('Biaya/emisi tahunan dan kapasitas menunjukkan tahun akhir; nilai kini mencakup seluruh periode. Tersimpan selama sesi browser ini.')
        st.dataframe(pd.DataFrame(st.session_state.saved).round(2), hide_index=True)
        if st.button('Hapus perbandingan'):
            st.session_state.saved = []
            st.rerun()
    save_active(st.session_state)
    if len(st.session_state['experiment_cases']) > 1:
        st.subheader('Ringkasan seluruh skenario eksperimen')
        overview = pd.DataFrame(case_overview(st.session_state))
        st.dataframe(overview.round(3), hide_index=True, width='stretch')
        st.caption('Hasil muncul setelah skenario dihitung. Input yang berubah harus dihitung ulang. '
                   'Periksa tahun akhir, model, dan asumsi tiap skenario saat membandingkan biaya dan emisi. '
                   'Data skenario dan hasil tersimpan selama sesi browser ini.')
        st.download_button('Unduh perbandingan skenario CSV', overview.to_csv(index=False).encode('utf-8-sig'),
                           'perbandingan_skenario.csv', 'text/csv')
