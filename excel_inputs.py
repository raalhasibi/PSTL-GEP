"""Impor input XLSX GENORA tanpa menjalankan solver atau memutasi sesi."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from model import BatteryConfig, POTENTIAL_COLUMN, build_problem, example_inputs, validate_names
from storage_inputs import STORAGE_COLUMNS, empty_storage_table, storage_configs
from stochastic import MAX_SCENARIOS, uncertainty_catalog
from year_profiles import LOAD_PERCENT, make_annual_profiles, validate_shape
from exogenous import EXOGENOUS_COLUMNS, empty_exogenous, validate_exogenous


TEMPLATE_PATH = Path(__file__).parent/'templates'/'GENORA_template.xlsx'
MODELS = ['Kontinu (LP)', 'Blok integer (MILP)', 'Blok integer + penyimpanan (MILP)']
INHERIT = ['Gunakan data tahun dasar', 'Edit per tahun']
PROJECTIONS = ['Pertumbuhan tahunan', 'Manual per tahun']
AVAIL = 'Availability (0–1)'
BAT_KEYS = dict(zip(STORAGE_COLUMNS.values(), [
    'bat_existing', 'bat_block', 'bat_duration', 'bat_max', 'bat_om_power_v2',
    'bat_om_energy_v2', 'bat_eff', 'bat_variable', 'bat_capex_power', 'bat_capex_energy', 'bat_lifetime']))
# label, state key, default, kind/choices, minimum, maximum, guidance
SETTINGS = [
    ('Versi format', 'format_version', 1, int, 1, 1, 'Gunakan 1.'),
    ('Tahun dasar', 'base_year', 2025, int, 1900, 2200, 'Tahun data kapasitas dan profil awal.'),
    ('Periode perencanaan (tahun)', 'planning_years', 5, int, 1, 50, '2025 + 5 tahun mengoptimasi 2026–2030.'),
    ('Model kapasitas', 'capacity_model_choice', MODELS[0], MODELS, None, None, 'Pilih salah satu pilihan pada dropdown.'),
    ('Beban puncak tahun dasar (MW)', 'base_peak_mw', 100., float, .001, None, 'Profil persen dikalikan nilai ini.'),
    ('Pertumbuhan beban tahunan (%)', 'load_growth', 0., float, -20., 20., 'Isi 5 untuk pertumbuhan 5%.'),
    ('Harga karbon (USD/tCO2)', 'carbon_input', 0., float, 0., None, 'Berlaku pada setiap tahun.'),
    ('Tingkat diskonto (%)', 'discount_input', 8., float, 0., 100., 'Isi 8 untuk diskonto 8%.'),
    ('Batasi emisi tahunan', 'emissions_enabled', 'TIDAK', bool, None, None, 'YA atau TIDAK.'),
    ('Batas emisi (tCO2/tahun)', 'emissions_input', 200000., float, 0., None, 'Digunakan jika batas emisi diaktifkan.'),
    ('Aktifkan stokastik', 'stochastic_enabled', 'TIDAK', bool, None, None, 'YA atau TIDAK; probabilitas gabungan ada di Stokastik.'),
    ('Metode proyeksi beban', 'load_projection_mode', PROJECTIONS[0], PROJECTIONS, None, None, 'Pertumbuhan tahunan atau Manual per tahun.'),
    ('Pola beban tahun berikutnya', 'load_shape_mode', INHERIT[0], INHERIT, None, None, 'Edit per tahun memakai baris tahun khusus di Profil Beban.'),
    ('Availability tahun berikutnya', 'availability_mode', INHERIT[0], INHERIT, None, None, 'Edit per tahun memakai baris tahun khusus di Availability.'),
    ('Solver optimisasi', 'solver_choice', 'HiGHS', ['HiGHS', 'Gurobi'], None, None, 'Gurobi memerlukan lisensi yang tersedia pada komputer/server.'),
    ('Lisensi Gurobi', 'gurobi_license_mode', 'Komputer/server (lisensi terpasang)',
     ['Komputer/server (lisensi terpasang)', 'Cloud (WLS)'], None, None, 'Kredensial WLS diatur pada aplikasi atau server, bukan di Excel.'),
]


class ExcelInputError(ValueError):
    def __init__(self, sheet, row, column, message):
        self.errors = [{'Sheet': sheet, 'Baris': row, 'Kolom': column, 'Pesan': message}]
        super().__init__(f'{sheet}, baris {row}, kolom {column}: {message}')


@dataclass
class ExcelInputs:
    snapshot: dict
    summary: pd.DataFrame


def fail(sheet, row, column, message):
    raise ExcelInputError(sheet, row, column, message)


def number(value, sheet, row, column, minimum=0., maximum=None, integer=False):
    if isinstance(value, (bool, np.bool_)) or value is None or str(value).strip() == '':
        fail(sheet, row, column, 'Isi angka; nilai kosong tidak dianggap nol.')
    try:
        result = float(value)
    except (TypeError, ValueError):
        fail(sheet, row, column, 'Harus berupa angka.')
    if not np.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        fail(sheet, row, column, f'Angka harus hingga dan sekurangnya {minimum:g}'+(f', maksimum {maximum:g}.' if maximum is not None else '.'))
    if integer and not result.is_integer():
        fail(sheet, row, column, 'Harus berupa bilangan bulat.')
    return int(result) if integer else result


def require(frames, sheet, columns, allow_empty=False):
    if sheet not in frames:
        fail(sheet, 1, 'Sheet', 'Sheet wajib tidak ditemukan.')
    frame = frames[sheet].copy()
    if not set(columns).issubset(frame.columns):
        fail(sheet, 1, 'Header', 'Kolom wajib: '+', '.join(columns))
    if not allow_empty and frame.empty:
        fail(sheet, 2, 'Data', 'Tabel wajib diisi.')
    unknown = set(frame.columns)-set(columns)
    if unknown:
        fail(sheet, 1, 'Header', 'Kolom tidak dikenal: '+', '.join(map(str, unknown)))
    return frame.reset_index(drop=True)


def validate_excel_frames(frames):
    setting_frame = require(frames, 'Pengaturan', ['Parameter', 'Nilai', 'Keterangan'])
    controls, rows = {}, {}
    for i, row in setting_frame.iterrows():
        label = str(row.Parameter).strip()
        if label in rows:
            fail('Pengaturan', i+2, 'Parameter', 'Parameter berulang.')
        rows[label] = (i+2, row.Nilai)
    if set(rows)-{s[0] for s in SETTINGS}:
        bad = next(key for key in rows if key not in {s[0] for s in SETTINGS})
        fail('Pengaturan', rows[bad][0], 'Parameter', f'Parameter tidak dikenal: {bad}.')
    for label, key, default, kind, minimum, maximum, _ in SETTINGS:
        if label not in rows:
            if label not in ('Solver optimisasi', 'Lisensi Gurobi'):
                fail('Pengaturan', 1, label, 'Parameter wajib belum diisi.')
            row, value = 0, default
        else:
            row, value = rows[label]
        if kind in (int, float):
            value = number(value, 'Pengaturan', row, 'Nilai', minimum, maximum, kind is int)
        elif kind is bool:
            if isinstance(value, (bool, np.bool_)):
                value = bool(value)
            elif str(value).strip().upper() in ('YA', 'TIDAK'):
                value = str(value).strip().upper() == 'YA'
            else:
                fail('Pengaturan', row, 'Nilai', 'Gunakan YA atau TIDAK.')
        else:
            value = str(value).strip()
            if value not in kind:
                fail('Pengaturan', row, 'Nilai', 'Pilihan: '+', '.join(kind))
        controls[key] = value
    controls.pop('format_version')
    base = controls['base_year']
    years = list(range(base+1, base+controls['planning_years']+1))
    tech_columns = example_inputs()[0].columns.tolist()
    if 'Pembangkit' in frames and POTENTIAL_COLUMN not in frames['Pembangkit']:
        frames = dict(frames)
        frames['Pembangkit'] = frames['Pembangkit'].assign(**{POTENTIAL_COLUMN: 0.})
    tech = require(frames, 'Pembangkit', tech_columns)
    tech['Teknologi'] = tech.Teknologi.map(lambda v: str(v).strip() if pd.notna(v) else '')
    try:
        validate_names(tech.Teknologi.tolist())
    except ValueError as exc:
        fail('Pembangkit', 2, 'Teknologi', str(exc))
    for i, row in tech.iterrows():
        for column in tech_columns[1:]:
            minimum = 1. if column == 'Umur aset (tahun)' else (.01 if column == 'Ukuran blok (MW)' else 0.)
            tech.at[i, column] = number(row[column], 'Pembangkit', i+2, column, minimum)
        if tech.at[i, 'Batas kapasitas (MW)'] > 0 and tech.at[i, 'Kapasitas tahun dasar (MW)'] > tech.at[i, 'Batas kapasitas (MW)']:
            fail('Pembangkit', i+2, 'Batas kapasitas (MW)', 'Batas positif tidak boleh di bawah kapasitas tahun dasar; 0 berarti tanpa batas.')
        if tech.at[i, POTENTIAL_COLUMN] > 0 and tech.at[i, 'Kapasitas tahun dasar (MW)'] > tech.at[i, POTENTIAL_COLUMN]:
            fail('Pembangkit', i+2, POTENTIAL_COLUMN, 'Potensi positif tidak boleh di bawah kapasitas tahun dasar.')
    names = tech.Teknologi.tolist()
    exogenous = require(frames, 'Kapasitas Eksogen', EXOGENOUS_COLUMNS, allow_empty=True) if 'Kapasitas Eksogen' in frames else empty_exogenous()
    for i, row in exogenous.iterrows():
        exogenous.at[i, 'Tahun operasi'] = number(row['Tahun operasi'], 'Kapasitas Eksogen', i+2, 'Tahun operasi', years[0], years[-1], True)
        exogenous.at[i, 'Tambahan eksogen (MW)'] = number(row['Tambahan eksogen (MW)'], 'Kapasitas Eksogen', i+2, 'Tambahan eksogen (MW)', 0.)
        if row.Teknologi not in names:
            fail('Kapasitas Eksogen', i+2, 'Teknologi', 'Nama harus terdapat pada tabel Pembangkit.')
    try:
        exogenous = validate_exogenous(exogenous, tech, base, controls['planning_years'])
    except ValueError as exc:
        fail('Kapasitas Eksogen', 2, 'Kapasitas', str(exc))
    storage = require(frames, 'Penyimpanan', ['Teknologi']+list(STORAGE_COLUMNS), allow_empty=True)
    storage['Teknologi'] = storage.Teknologi.map(lambda v: str(v).strip() if pd.notna(v) else '')
    if storage.Teknologi.str.casefold().duplicated().any():
        fail('Penyimpanan', 2, 'Teknologi', 'Nama penyimpanan berulang.')
    try:
        validate_names(names+[n for n in storage.Teknologi if n != 'Baterai'])
    except ValueError as exc:
        fail('Penyimpanan', 2, 'Teknologi', str(exc))
    for i, row in storage.iterrows():
        for column in STORAGE_COLUMNS:
            minimum = .01 if column in ('Daya blok (MW)', 'Durasi (jam)', 'Efisiensi round-trip (0–1)') else (1. if column == 'Umur aset (tahun)' else 0.)
            storage.at[i, column] = number(row[column], 'Penyimpanan', i+2, column, minimum, 1. if column == 'Efisiensi round-trip (0–1)' else None)
        try:
            BatteryConfig(**{field: float(storage.at[i, col]) for col, field in STORAGE_COLUMNS.items()}).validate()
        except ValueError as exc:
            fail('Penyimpanan', i+2, 'Parameter penyimpanan', str(exc))
    default_battery = BatteryConfig(max_power_mw=0.)
    default_rows = storage[storage.Teknologi == 'Baterai']
    if not default_rows.empty:
        default_battery = BatteryConfig(**{field: float(default_rows.iloc[0][col]) for col, field in STORAGE_COLUMNS.items()})
    for field, key in BAT_KEYS.items():
        controls[key] = getattr(default_battery, field)*(100. if field == 'round_trip_efficiency' else 1.)
    extras = storage[storage.Teknologi != 'Baterai'].reset_index(drop=True)

    peaks_frame = require(frames, 'Beban Puncak', ['Tahun', 'Puncak beban (MW)'], allow_empty=True)
    peaks = {}
    for i, row in peaks_frame.iterrows():
        year = number(row.Tahun, 'Beban Puncak', i+2, 'Tahun', years[0], years[-1], True)
        if year in peaks:
            fail('Beban Puncak', i+2, 'Tahun', 'Tahun berulang.')
        peaks[year] = number(row['Puncak beban (MW)'], 'Beban Puncak', i+2, 'Puncak beban (MW)', .001)
    if controls['load_projection_mode'] == 'Manual per tahun' and set(peaks) != set(years):
        fail('Beban Puncak', 2, 'Tahun', 'Mode manual harus memuat seluruh tahun perencanaan: '+', '.join(map(str, years)))

    shapes_frame = require(frames, 'Profil Beban', ['Tahun', 'Jam', LOAD_PERCENT])
    for i, row in shapes_frame.iterrows():
        shapes_frame.at[i, 'Tahun'] = number(row.Tahun, 'Profil Beban', i+2, 'Tahun', base, years[-1], True)
        shapes_frame.at[i, 'Jam'] = number(row.Jam, 'Profil Beban', i+2, 'Jam', 0, 23, True)
        shapes_frame.at[i, LOAD_PERCENT] = number(row[LOAD_PERCENT], 'Profil Beban', i+2, LOAD_PERCENT, 0., 100.)
    shapes = {}
    for year, group in shapes_frame.groupby('Tahun', sort=False):
        table = group[['Jam', LOAD_PERCENT]].sort_values('Jam').reset_index(drop=True)
        try:
            validate_shape(table, range(24))
        except ValueError as exc:
            fail('Profil Beban', int(group.index[0])+2, f'Tahun {int(year)}', str(exc)+' Wajib tepat 24 jam unik (0–23).')
        shapes[int(year)] = table
    if base not in shapes:
        fail('Profil Beban', 2, 'Tahun', f'Profil tahun dasar {base} wajib diisi.')

    a_frame = require(frames, 'Availability', ['Tahun', 'Jam', 'Teknologi', AVAIL])
    for i, row in a_frame.iterrows():
        a_frame.at[i, 'Tahun'] = number(row.Tahun, 'Availability', i+2, 'Tahun', base, years[-1], True)
        a_frame.at[i, 'Jam'] = number(row.Jam, 'Availability', i+2, 'Jam', 0, 23, True)
        name = str(row.Teknologi).strip()
        if name not in names:
            fail('Availability', i+2, 'Teknologi', f'Teknologi tidak ditemukan di Pembangkit: {name}.')
        a_frame.at[i, 'Teknologi'] = name
        a_frame.at[i, AVAIL] = number(row[AVAIL], 'Availability', i+2, AVAIL, 0., 1.)
    for (year, name), group in a_frame.groupby(['Tahun', 'Teknologi'], sort=False):
        if sorted(group.Jam.tolist()) != list(range(24)):
            fail('Availability', int(group.index[0])+2, 'Jam', f'{name}, tahun {int(year)} wajib memiliki tepat 24 jam unik (0–23).')
    if set(a_frame.loc[a_frame.Tahun == base, 'Teknologi']) != set(names):
        fail('Availability', 2, 'Tahun', 'Availability tahun dasar wajib mencakup seluruh teknologi pembangkit.')
    availabilities = {int(year): group.pivot(index='Jam', columns='Teknologi', values=AVAIL).reset_index().rename_axis(None, axis=1)
                      for year, group in a_frame.groupby('Tahun', sort=False)}
    profile = availabilities.pop(base)[['Jam']+names].copy()
    profile.insert(1, 'Beban (MW)', shapes[base][LOAD_PERCENT].to_numpy(dtype=float)*controls['base_peak_mw']/100.)
    base_shape = shapes.pop(base)
    active_peaks = {year: peaks[year] if controls['load_projection_mode'] == 'Manual per tahun' else
                    controls['base_peak_mw']*(1.+controls['load_growth']/100.)**(year-base) for year in years}
    annual = make_annual_profiles(profile, base_shape, active_peaks,
        shapes if controls['load_shape_mode'] == 'Edit per tahun' else None,
        availabilities if controls['availability_mode'] == 'Edit per tahun' else None)
    use_storage = controls['capacity_model_choice'] == MODELS[2]
    options = dict(carbon_price=controls['carbon_input'], discount_rate=controls['discount_input']/100.,
        emissions_limit=controls['emissions_input'] if controls['emissions_enabled'] else None,
        capacity_model='continuous' if controls['capacity_model_choice'] == MODELS[0] else 'integer',
        battery=default_battery if use_storage else None, storages=storage_configs(extras) if use_storage else {})
    # Validasi struktur dan parameter saja, tanpa menjalankan solver.
    for year, frame in annual.items():
        try:
            build_problem(tech, frame, **options)
        except ValueError as exc:
            fail('Pengaturan', 2, f'Tahun {year}', str(exc))

    stoch = require(frames, 'Stokastik', ['Skenario', 'Probabilitas', 'Parameter', 'Nilai'], allow_empty=True)
    catalog = uncertainty_catalog(tech, **options)
    scenario_order, selected, probabilities, values = [], [], {}, {}
    for i, row in stoch.iterrows():
        label, parameter = str(row.Skenario).strip(), str(row.Parameter).strip()
        if pd.isna(row.Skenario) or not label:
            fail('Stokastik', i+2, 'Skenario', 'Nama skenario wajib diisi.')
        if parameter not in catalog:
            fail('Stokastik', i+2, 'Parameter', 'Parameter tidak dikenal/tersedia untuk model terpilih: '+parameter)
        prob = number(row.Probabilitas, 'Stokastik', i+2, 'Probabilitas', np.nextafter(0., 1.), 1.)
        spec = catalog[parameter]
        value = number(row.Nilai, 'Stokastik', i+2, 'Nilai', np.nextafter(0., 1.) if spec['positive'] else 0., spec['maximum'])
        if label in probabilities and not np.isclose(probabilities[label], prob, rtol=0., atol=1e-10):
            fail('Stokastik', i+2, 'Probabilitas', 'Probabilitas pada satu skenario harus sama pada seluruh baris parameternya.')
        if (label, parameter) in values:
            fail('Stokastik', i+2, 'Parameter', 'Parameter berulang pada skenario yang sama.')
        if label not in scenario_order:
            scenario_order.append(label)
        if parameter not in selected:
            selected.append(parameter)
        probabilities[label] = prob
        values[label, parameter] = value
    if stoch.empty and controls['stochastic_enabled']:
        fail('Stokastik', 2, 'Data', 'Isi skenario dan parameter ketika model stokastik aktif.')
    if scenario_order:
        if not 2 <= len(scenario_order) <= MAX_SCENARIOS or len({s.casefold() for s in scenario_order}) != len(scenario_order):
            fail('Stokastik', 2, 'Skenario', f'Gunakan 2–{MAX_SCENARIOS} nama skenario unik.')
        if not np.isclose(sum(probabilities.values()), 1., rtol=0., atol=1e-8):
            fail('Stokastik', 2, 'Probabilitas', 'Jumlah probabilitas per skenario unik harus 1.')
        if len(values) != len(scenario_order)*len(selected):
            fail('Stokastik', 2, 'Parameter', 'Setiap skenario harus mengisi kumpulan parameter yang sama.')
    scenarios = pd.DataFrame([{'Skenario': name, 'Probabilitas': probabilities[name],
        **{parameter: values[name, parameter] for parameter in selected}} for name in scenario_order])
    if scenario_order:
        controls['uncertain_parameters'] = selected
        controls['stochastic_count'] = len(scenario_order)
    snapshot = {**controls, 'technology_inputs_v2': tech, 'profile_inputs_v2': profile,
        'base_load_shape': base_shape, 'annual_load_shapes': shapes, 'annual_availabilities': availabilities,
        'storage_inputs': extras if not extras.empty else empty_storage_table(), 'manual_forecast_inputs': peaks,
        'input_revision_v2': 0, 'storage_revision': 0, 'exogenous_inputs': exogenous}
    if scenario_order:
        snapshot['stochastic_inputs'] = scenarios
    summary = pd.DataFrame([
        {'Input': 'Tahun dasar / akhir', 'Isi': f'{base} / {years[-1]}'},
        {'Input': 'Model kapasitas', 'Isi': controls['capacity_model_choice']},
        {'Input': 'Solver', 'Isi': controls['solver_choice']},
        {'Input': 'Teknologi pembangkit', 'Isi': str(len(tech))},
        {'Input': 'Tambahan kapasitas eksogen (MW)', 'Isi': str(exogenous['Tambahan eksogen (MW)'].sum())},
        {'Input': 'Jenis penyimpanan dalam file', 'Isi': str(len(storage))},
        {'Input': 'Tahun dengan profil beban khusus', 'Isi': ', '.join(map(str, shapes)) or 'Tidak ada'},
        {'Input': 'Tahun dengan availability khusus', 'Isi': ', '.join(map(str, availabilities)) or 'Tidak ada'},
        {'Input': 'Skenario stokastik dalam file', 'Isi': str(len(scenario_order))},
    ])
    return ExcelInputs(snapshot, summary)


def default_template_frames():
    tech, profile = example_inputs()
    battery = BatteryConfig()
    settings = pd.DataFrame([{'Parameter': label, 'Nilai': default, 'Keterangan': note}
        for label, _, default, _, _, _, note in SETTINGS])
    guide = [
        ('GENORA', 'Template input satu skenario eksperimen. Semua angka contoh bersifat ilustratif.'),
        ('Alur', 'Isi workbook, simpan sebagai .xlsx, unggah, Periksa Excel, lalu Terapkan ke skenario aktif. Jalankan Optimisasi secara terpisah.'),
        ('Struktur', 'Pertahankan nama sheet dan header baris 1. Tambahkan baris data bila diperlukan. Jangan gabungkan sel pada tabel input.'),
        ('Angka', 'Gunakan angka biasa. Profil beban 60 berarti 60%; availability 0,6 berarti 60%. Diskonto 8 berarti 8%.'),
        ('Pengaturan', 'Versi format 1. Pilihan YA/TIDAK dan model harus sama dengan dropdown. Ubah tahun dan periode sesuai kebutuhan.'),
        ('Pembangkit', 'Nama unik. Kapasitas tahun dasar dan seluruh biaya wajib diisi. Batas kapasitas 0 = tanpa batas; positif = total lama + baru.'),
        ('Penyimpanan', 'Baterai adalah nama khusus baterai default. Tambahkan jenis lain dengan nama unik. Hapus semua baris untuk tanpa penyimpanan.'),
        ('Penyimpanan aktif', 'Penyimpanan dipakai jika Model kapasitas = Blok integer + penyimpanan (MILP). Batas daya 0 menonaktifkan penyimpanan.'),
        ('Beban Puncak', 'Hanya tahun setelah tahun dasar. Mode Manual per tahun wajib mengisi setiap tahun; Pertumbuhan tahunan memakai persen di Pengaturan.'),
        ('Profil Beban', 'Tahun dasar wajib tepat 24 baris, jam 0–23 unik. Profil 0–100 dan minimal satu jam 100. Jumlah antarjam tidak perlu 100.'),
        ('Profil tahun berikutnya', 'Tambahkan 24 baris untuk tahun khusus dan pilih Pola beban tahun berikutnya = Edit per tahun. Tahun lain mewarisi tahun dasar.'),
        ('Availability', 'Format panjang: satu baris per tahun, jam, teknologi. Tahun dasar harus memuat semua pembangkit, masing-masing 24 jam.'),
        ('Availability tahun berikutnya', 'Tambahkan 24 baris per teknologi yang diubah dan pilih Availability tahun berikutnya = Edit per tahun. Teknologi lain mewarisi data dasar.'),
        ('Stokastik', 'Format panjang: nama skenario, probabilitas, nama parameter persis seperti aplikasi, dan nilai. Tiap skenario mengisi parameter yang sama.'),
        ('Probabilitas', 'Probabilitas diulang sama pada baris parameter milik skenario yang sama. Jumlah probabilitas skenario unik harus 1, bukan jumlah semua baris.'),
        ('Stokastik nonaktif', 'Sheet boleh hanya berisi header. Untuk mengaktifkan, pilih YA dan isi 2–50 skenario. Nama parameter mengikuti teknologi/model yang dipilih.'),
        ('Rumus Excel', 'Angka langsung disarankan. Jika memakai rumus, hitung dan simpan dengan Excel terlebih dahulu agar nilai hasil rumus tersedia saat dibaca.'),
        ('Impor', 'Hanya input skenario aktif diganti setelah validasi. Hasil optimisasi lama skenario aktif dihapus; skenario lain tetap tersimpan.'),
        ('Kapasitas Eksogen', 'Opsional: isi tahun operasi setelah tahun dasar, teknologi, dan tambahan MW. Kapasitas tersedia sejak tahun operasi; biaya mengikuti Pembangkit. Kosong = tanpa proyek.'),
        ('Solver', 'Pilih HiGHS atau Gurobi di Pengaturan. Mode lisensi Gurobi dapat lokal/server atau Cloud (WLS). Kredensial tidak disimpan dalam workbook.'),
        ('Potensi EBT', 'Kolom Potensi EBT (MW) di Pembangkit membatasi total kapasitas dasar + eksogen + endogen. 0 = tanpa batas potensi. Batas kapasitas umum tetap berlaku. Gunakan data sumber daya.'),
    ]
    stochastic_rows = []
    for label, prob, load, solar, wind in [('Ringan', .25, .9, 1.1, 1.1), ('Normal', .5, 1., 1., 1.), ('Berat', .25, 1.1, .8, .7)]:
        for parameter, value in [('Faktor beban', load), ('Faktor PLTS', solar), ('Faktor PLTB', wind)]:
            stochastic_rows.append({'Skenario': label, 'Probabilitas': prob, 'Parameter': parameter, 'Nilai': value})
    return {
        'Petunjuk': pd.DataFrame(guide, columns=['Bagian', 'Petunjuk pengisian']),
        'Pengaturan': settings,
        'Pembangkit': tech,
        'Kapasitas Eksogen': empty_exogenous(),
        'Penyimpanan': pd.DataFrame([{'Teknologi': 'Baterai', **{col: getattr(battery, attr) for col, attr in STORAGE_COLUMNS.items()}}]),
        'Beban Puncak': pd.DataFrame({'Tahun': range(2026, 2031), 'Puncak beban (MW)': [100.]*5}),
        'Profil Beban': pd.DataFrame({'Tahun': [2025]*24, 'Jam': profile.Jam, LOAD_PERCENT: profile['Beban (MW)']}),
        'Availability': pd.DataFrame([{'Tahun': 2025, 'Jam': int(row.Jam), 'Teknologi': name, AVAIL: float(row[name])}
            for name in tech.Teknologi for _, row in profile.iterrows()]),
        'Stokastik': pd.DataFrame(stochastic_rows),
    }


def read_excel_inputs(data):
    if not data or len(data) > 10*1024*1024:
        fail('File', 0, 'Ukuran', 'Unggah file .xlsx yang tidak kosong, maksimum 10 MB.')
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 50*1024*1024:
                fail('File', 0, 'Ukuran', 'Isi workbook terlalu besar (maksimum 50 MB setelah dibuka).')
        book = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
        frames = {}
        for sheet in book:
            if sheet.title == 'Petunjuk':
                continue
            if sheet.max_row is None or sheet.max_column is None:
                sheet.calculate_dimension(force=True)
            if sheet.max_row > 50000 or sheet.max_column > 64:
                fail(sheet.title, 1, 'Ukuran', 'Maksimum 50.000 baris dan 64 kolom per sheet.')
            rows = list(sheet.values)
            if not rows:
                continue
            header = list(rows[0])
            while header and header[-1] is None:
                header.pop()
            if any(not isinstance(c, str) or not c.strip() for c in header) or len(set(header)) != len(header):
                fail(sheet.title, 1, 'Header', 'Header wajib berupa teks unik tanpa kolom kosong di tengah.')
            body = [list(row[:len(header)]) for row in rows[1:]]
            # Pertahankan posisi baris untuk pesan kesalahan. Hanya hapus baris kosong di akhir.
            while body and all(v is None for v in body[-1]):
                body.pop()
            frames[sheet.title] = pd.DataFrame(body, columns=header)
        book.close()
        return validate_excel_frames(frames)
    except ExcelInputError:
        raise
    except Exception as exc:
        fail('File', 0, 'Workbook', 'File tidak dapat dibaca sebagai template GENORA: '+str(exc))
