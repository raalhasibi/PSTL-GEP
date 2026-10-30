import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from model import BatteryConfig, add_technology, example_inputs, solve, validate_names
from stochastic import MAX_SCENARIOS, example_scenarios, resize_scenarios, solve_stochastic, uncertainty_catalog
from storage_inputs import STORAGE_COLUMNS, add_storage, empty_storage_table, storage_configs

STORAGE_MODEL_LABEL = 'Blok integer + penyimpanan (MILP)'

st.set_page_config(page_title='Lab Kapasitas Pembangkit', page_icon='⚡', layout='wide')
st.title('⚡ Lab Kapasitas Pembangkit')
st.write('Eksperimen perencanaan kapasitas satu node untuk pembelajaran mahasiswa.')
st.info('Data ilustratif • 24 jam contoh × 365 hari • Semua kapasitas dibangun baru • Satu node tanpa transmisi')

if st.session_state.pop('activate_storage_model', False):
    st.session_state['capacity_model_choice'] = STORAGE_MODEL_LABEL

with st.sidebar:
    st.header('Pengaturan eksperimen')
    scenario = st.text_input('Nama skenario', 'Skenario dasar')
    model_label = st.radio('Model kapasitas', ['Kontinu (LP)', 'Blok integer (MILP)', STORAGE_MODEL_LABEL], key='capacity_model_choice')
    integer = model_label != 'Kontinu (LP)'
    use_battery = model_label == STORAGE_MODEL_LABEL
    st.caption('Kontinu: kapasitas bebas. Integer: kapasitas kelipatan ukuran blok; dispatch tetap kontinu.')
    peak = st.number_input('Puncak beban contoh (MW)', min_value=1., max_value=10000., value=100., step=10.)
    carbon = st.number_input('Harga karbon (USD/tCO2)', min_value=0., value=0., step=10.)
    discount_rate = st.number_input('Tingkat diskonto (%)', min_value=0., max_value=100., value=8., step=1.)/100
    use_limit = st.checkbox('Batasi emisi tahunan')
    limit = st.number_input('Batas emisi (tCO2/tahun)', min_value=0., value=200000., step=10000.) if use_limit else None
    stochastic = st.checkbox('Aktifkan model stokastik dua tahap')
    if stochastic:
        st.caption('Kapasitas bersama untuk semua skenario; biaya minimum ekspektasian. '
                   'Beban dan batas emisi wajib dipenuhi pada SETIAP skenario.')
    st.caption('Puncak beban membentuk profil awal. Tabel profil dapat diedit lebih lanjut.')

tech, profiles = example_inputs(peak)
if 'storage_inputs' not in st.session_state:
    st.session_state['storage_inputs'] = empty_storage_table()
    st.session_state['storage_revision'] = 0
if 'technology_inputs_v2' not in st.session_state:
    st.session_state['technology_inputs_v2'] = tech.copy()
    st.session_state['profile_inputs_v2'] = profiles.copy()
    st.session_state['input_revision_v2'] = 0
    st.session_state['profile_peak_v2'] = peak
elif st.session_state['profile_peak_v2'] != peak:
    updated_profile = st.session_state['profile_inputs_v2'].copy()
    updated_profile['Beban (MW)'] = profiles['Beban (MW)'].to_numpy()
    st.session_state['profile_inputs_v2'] = updated_profile
    st.session_state['profile_peak_v2'] = peak
inputs, theory = st.tabs(['1 · Input & hasil', '2 · Model matematika'])
with theory:
    st.subheader('Apa yang diputuskan model?')
    st.write('Kapasitas terpasang setiap teknologi Kᵢ (MW) dan produksi setiap jam pᵢₜ (MW). '
             'Model memilih kombinasi dengan total biaya tahunan minimum.')
    st.latex(r'\min\ \sum_i 1000\,(I_i\,CRF(r,L_i)+F_i)K_i + \sum_{i,t}365\,(V_i + q e_i)p_{i,t}')
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
             'Model tetap satu tahun representatif, bukan jadwal investasi multiyear.')
    if use_battery:
        st.latex(r'\sum_i p_{i,t}+\sum_b d_{b,t}=D_t+\sum_b c_{b,t}\quad\forall t')
    else:
        st.latex(r'\sum_i p_{i,t}=D_t\quad\forall t')
    st.latex(r'0\le p_{i,t}\le a_{i,t}K_i,\qquad 0\le K_i\le K_i^{max}')
    if integer:
        st.latex(r'K_i=B_i N_i,\quad N_i\in\mathbb{Z}_{\ge 0},\quad N_i\le\lfloor K_i^{max}/B_i\rfloor')
        st.write('Bᵢ adalah ukuran blok (MW), Nᵢ jumlah blok yang dibangun. Contoh: blok 50 MW '
                 'memungkinkan kapasitas 0, 50, 100, 150 MW. Batas 120 MW hanya mengizinkan 2 blok. '
                 'Jumlah blok dioptimasi langsung oleh HiGHS, bukan pembulatan hasil LP.')
    else:
        st.write('Model kontinu (LP): Kᵢ dapat bernilai pecahan, misalnya 37,5 MW.')
    st.latex(r'\sum_{i,t}365\,e_i p_{i,t}\le E^{max}\quad\text{(opsional)}')
    if use_battery:
        st.subheader('Penyimpanan: daya, energi, dan operasi')
        st.write('Persamaan berikut berlaku TERPISAH untuk setiap jenis penyimpanan b. '
                 'Biaya sistem menjumlahkan biaya seluruh jenis. Energi tidak dapat berpindah antarjenis tanpa melalui node listrik.')
        st.latex(r'N_b\in\mathbb{Z}_{\ge0},\quad P_b=B_b N_b,\quad E_b=H_b P_b')
        st.latex(r'S_{t+1}=S_t+\eta_c c_t-d_t/\eta_d,\quad 0\le S_t\le E_b,\quad S_{24}=S_0')
        st.latex(r'0\le c_t,d_t\le P_b,\quad c_t\le Mz_t,\quad d_t\le M(1-z_t),\quad z_t\in\{0,1\}')
        st.latex(r'A_b=1000(I_P P_b+I_E E_b),\quad C_b=CRF(r,L_b)A_b+1000(F_P P_b+F_E E_b)+365\sum_t V_b d_t')
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
    st.subheader('Teknologi pembangkit')
    st.caption('Investasi adalah biaya awal per kW, sedangkan O&M tetap hanya biaya operasi tahunan. '
               'Semua data awal dan nilai awal formulir adalah ilustrasi untuk mengajar.')
    if st.button('Tambah Teknologi', key='show_add_technology'):
        st.session_state['adding_technology'] = not st.session_state.get('adding_technology', False)
    if st.session_state.get('technology_notice'):
        st.success(st.session_state.pop('technology_notice'))
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
                new_maximum = f1.number_input('Batas kapasitas teknologi baru (MW)', min_value=0., value=300.)
                new_lifetime = f2.number_input('Umur aset teknologi baru (tahun)', min_value=1., value=25.)
                new_block = f1.number_input('Ukuran blok teknologi baru (MW)', min_value=.01, value=10.)
                new_profile = st.selectbox('Profil awal teknologi baru', ['Konstan', 'Contoh PLTS', 'Contoh PLTB'])
                new_availability = st.number_input('Ketersediaan konstan teknologi baru (0–1)', min_value=0., max_value=1., value=.9)
                st.caption('Nilai konstan dipakai hanya untuk profil Konstan. Profil awal dapat diedit per jam setelah ditambahkan. '
                           'Nama harus unik; untuk menonaktifkan teknologi, ubah batas kapasitasnya menjadi nol.')
                submitted = st.form_submit_button('Tambahkan ke model')
            if submitted:
                template = new_availability if new_profile == 'Konstan' else profiles['PLTS' if new_profile == 'Contoh PLTS' else 'PLTB'].to_numpy()
                try:
                    validate_names(st.session_state['technology_inputs_v2'].Teknologi.tolist()
                                   +st.session_state['storage_inputs'].Teknologi.tolist()+[new_name.strip()])
                    added, added_profiles = add_technology(st.session_state['technology_inputs_v2'], st.session_state['profile_inputs_v2'],
                        new_name, new_investment, new_om, new_variable, new_emissions, new_maximum, new_lifetime, new_block, template)
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
                    config = BatteryConfig(sb, sh, sm, sfp, sfe, se/100, sv, sip, sie, sl)
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
    technology = st.data_editor(tech, hide_index=True, disabled=['Teknologi'],
        key=f"technology_v2_{st.session_state['input_revision_v2']}", column_config=configs,
        column_order=['Teknologi', 'Investasi (USD/kW)', 'Umur aset (tahun)', 'O&M tetap (USD/kW/tahun)',
                      'Biaya variabel (USD/MWh)', 'Emisi (tCO2/MWh)', 'Batas kapasitas (MW)', 'Ukuran blok (MW)'])
    st.session_state['technology_inputs_v2'] = technology.copy()
    block_sizes = dict(zip(technology.Teknologi, technology['Ukuran blok (MW)'])) if integer else None
    st.caption('Ukuran blok dipakai pada model integer. Batas kapasitas yang tidak mencapai satu blok penuh tidak dapat dibangun.')
    battery = None
    extra_storage_table = empty_storage_table()
    if use_battery:
        st.subheader('Penyimpanan energi dalam blok integer')
        st.caption('Setiap jenis dioptimasi bersama dengan pembangkit dan boleh memiliki nol blok. '
                   'Nonaktifkan baterai default dengan batas daya nol jika hanya ingin memakai jenis tambahan.')
        with st.expander('Parameter baterai default', expanded=True):
            b1, b2 = st.columns(2)
            block_mw = b1.number_input('Daya per blok baterai (MW)', min_value=0.01, value=10., key='bat_block')
            duration = b2.number_input('Durasi baterai (jam)', min_value=0.01, value=4., key='bat_duration')
            max_power = b1.number_input('Batas daya baterai (MW)', min_value=0., value=200., key='bat_max')
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
                                discharge_cost, investment_power, investment_energy, battery_lifetime)
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
    with st.expander('Edit beban dan ketersediaan per jam'):
        st.caption('Nilai 0,5 berarti maksimum produksi pada jam tersebut adalah 50% dari kapasitas terpasang.')
        profile = st.data_editor(st.session_state['profile_inputs_v2'], hide_index=True, disabled=['Jam'],
                                 key=f"profiles_v2_{st.session_state['input_revision_v2']}_{peak}",
                                 column_config={'Beban (MW)': st.column_config.NumberColumn(min_value=0.),
                                                **{n: st.column_config.NumberColumn(min_value=0., max_value=1.) for n in tech.Teknologi}})
    st.session_state['profile_inputs_v2'] = profile.copy()
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
        'scenario': scenario, 'model': model_label, 'carbon': carbon, 'limit': limit, 'discount_rate': discount_rate,
        'technology': technology.to_json(orient='split', double_precision=15),
        'profile': profile.to_json(orient='split', double_precision=15),
        'blocks': block_sizes, 'battery': vars(battery) if battery else None,
        'storages': extra_storage_table.to_json(orient='split', double_precision=15),
        'stochastic': stochastic,
        'uncertainty_scenarios': scenario_table.to_json(orient='split', double_precision=15) if stochastic else None,
        'uncertainty_parameters': selected_parameters if stochastic else [],
    }, sort_keys=True)
    st.caption('Selesaikan perubahan input (Enter atau klik sel lain), lalu tekan tombol di bawah. '
               'Optimisasi hanya dijalankan ketika tombol ditekan.')
    if st.button('Jalankan Optimisasi', type='primary', key='run_optimization'):
        with st.spinner('Menjalankan optimisasi...'):
            try:
                options = dict(carbon_price=carbon, emissions_limit=limit,
                               capacity_model='integer' if integer else 'continuous',
                               block_sizes=block_sizes, battery=battery, discount_rate=discount_rate,
                               storages=storage_configs(extra_storage_table))
                computed = solve_stochastic(technology, profile, scenario_table, uncertainty_parameters=selected_parameters,
                                             **options) if stochastic else solve(technology, profile, **options)
                st.session_state['optimization'] = {'signature': signature, 'result': computed}
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
        st.subheader(f'Hasil · {scenario}')
        st.caption(f'Model: {model_label} · Solver: HiGHS')
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
            all_dispatch = pd.concat([r.dispatch.assign(Skenario=name) for name, r in result.scenario_results.items()], ignore_index=True)
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
        investment_label = 'Ekspektasi investasi awal total' if stochastic else 'Investasi awal total'
        st.write(f'**{investment_label}: {total_investment/1e6:,.2f} juta USD** · '
                 f'Investasi yang ditahunkan: {annual_investment/1e6:,.2f} juta USD/tahun · Diskonto {discount_rate:.1%}')
        st.caption('Biaya tetap pada tabel hasil = investasi tahunan + O&M tetap. '
                   'Kolom rincian investasi dan O&M bukan biaya tambahan di luar biaya tetap tersebut.')
        left, right = st.columns(2)
        capacity_table = result.summary[['Teknologi', 'Kapasitas (MW)']].copy()
        if use_battery:
            for _, row in result.storage_summary.iterrows():
                capacity_table.loc[len(capacity_table)] = [row['Teknologi'], row['Daya (MW)']]
        left.plotly_chart(px.bar(capacity_table, x='Teknologi', y='Kapasitas (MW)', color='Teknologi',
                                 title='Kapasitas optimal'), width='stretch')
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
        fig.update_layout(title='Operasi pembangkit: satu hari contoh', xaxis_title='Jam', yaxis_title='MW')
        if use_battery:
            fig.add_hline(y=0, line_color='gray', line_width=1)
        right.plotly_chart(fig, width='stretch')
        if use_battery:
            st.caption('Grafik dispatch: pengisian setiap penyimpanan negatif, pelepasan positif. '
                       'Total pembangkitan + pelepasan − pengisian = beban. '
                       'Area pengisian ditumpuk terpisah di bawah nol.')
        st.dataframe(result.summary.round(2), hide_index=True, width='stretch')
        st.download_button('Unduh ringkasan CSV', result.summary.to_csv(index=False).encode('utf-8-sig'), 'ringkasan.csv', 'text/csv')
        st.download_button('Unduh dispatch CSV', display_dispatch.to_csv(index=False).encode('utf-8-sig'), 'dispatch.csv', 'text/csv')
        if use_battery:
            st.subheader('Kapasitas & operasi penyimpanan')
            ba, bb, bc = st.columns(3)
            ba.metric('Jumlah blok penyimpanan (total)', f"{int(result.storage_summary['Jumlah blok'].sum())}")
            bb.metric('Total daya penyimpanan', f"{result.storage_summary['Daya (MW)'].sum():,.1f} MW")
            bc.metric('Total energi penyimpanan', f"{result.storage_summary['Energi (MWh)'].sum():,.1f} MWh")
            if result.storage_summary['Jumlah blok'].sum() == 0:
                st.info('Penyimpanan belum ekonomis atau belum dibutuhkan pada input ini; nol blok adalah solusi yang valid.')
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
            saved = st.session_state.setdefault('saved', [])
            saved.append({'Skenario': scenario, 'Model': model_label,
                          'Pendekatan': 'Stokastik dua tahap' if stochastic else 'Deterministik',
                          'Skenario ketidakpastian': scenario_table.to_json(orient='records') if stochastic else '—',
                          'Parameter tidak pasti': ', '.join(selected_parameters) if stochastic else '—',
                          'Ukuran blok (MW)': str(block_sizes) if integer else '—',
                          'Biaya (juta USD/tahun)': result.annual_cost/1e6,
                          'Emisi (ribu tCO2/tahun)': result.annual_emissions/1000,
                          'Diskonto (%)': discount_rate*100,
                          'Investasi awal (juta USD)': total_investment/1e6,
                          'Investasi tahunan (juta USD/tahun)': annual_investment/1e6,
                          'Penyimpanan (MW)': result.storage_summary['Daya (MW)'].sum() if use_battery else 0.,
                          'Penyimpanan (MWh)': result.storage_summary['Energi (MWh)'].sum() if use_battery else 0.,
                          'Parameter baterai': str(vars(battery)) if use_battery else '—',
                          'Parameter penyimpanan': extra_storage_table.to_json(orient='records') if use_battery else '—',
                          'Penyimpanan per teknologi': result.storage_summary.to_json(orient='records') if use_battery else '—',
                          **dict(zip(result.summary.Teknologi, result.summary['Kapasitas (MW)']))})
    if st.session_state.get('saved'):
        st.subheader('Perbandingan hasil tersimpan')
        st.caption('Kolom teknologi menunjukkan kapasitas dalam MW. Tersimpan selama sesi browser ini.')
        st.dataframe(pd.DataFrame(st.session_state.saved).round(2), hide_index=True)
        if st.button('Hapus perbandingan'):
            st.session_state.saved = []
            st.rerun()
