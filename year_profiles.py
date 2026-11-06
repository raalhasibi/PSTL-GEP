"""Profil persentase dan availability per tahun menjadi input fisik solver."""
import numpy as np
import pandas as pd


LOAD_PERCENT = 'Profil beban (% puncak)'
LOAD_PRESETS = ('Manual', 'Flat', 'Selisih puncak–dasar tinggi', 'Selisih puncak–dasar moderat')


def preset_load_shape(hours, preset):
    """Pola harian ilustratif; dasar 40% / 70%, puncak pukul 19."""
    hours = list(hours)
    h = np.asarray(hours, dtype=float)
    if not len(h) or not np.isfinite(h).all() or (h < 0).any() or (h > 23).any() or (h != np.floor(h)).any() or len(set(hours)) != len(hours):
        raise ValueError('Profil otomatis memerlukan jam unik berupa bilangan bulat 0–23.')
    if preset not in LOAD_PRESETS[1:]:
        raise ValueError('Pilih pola otomatis yang tersedia.')
    if preset == 'Flat':
        values = np.full(len(h), 100.)
    else:
        # Malam/dini hari rendah, naik pada siang hari, puncak malam.
        daily = np.array([.20, .13, .06, 0., .04, .15, .30, .45,
                          .55, .60, .65, .70, .68, .63, .60, .62,
                          .72, .85, .95, 1., .90, .72, .50, .32])
        sampled = daily[h.astype(int)]
        amplitude = float(np.ptp(sampled))
        unit = (sampled-sampled.min())/amplitude if amplitude > 0 else np.ones(len(h))
        minimum = 40. if preset == LOAD_PRESETS[2] else 70.
        values = np.round(minimum+(100.-minimum)*unit, 2)
    return pd.DataFrame({'Jam': hours, LOAD_PERCENT: values})


def validate_shape(table, hours):
    if table['Jam'].tolist() != list(hours):
        raise ValueError('Jam profil beban harus sama dengan jam tahun dasar.')
    values = table[LOAD_PERCENT].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (values > 100).any():
        raise ValueError('Profil beban harus berupa angka antara 0 dan 100 persen.')
    if not np.isclose(values.max(), 100., atol=1e-8, rtol=0.):
        raise ValueError('Profil beban harus mencapai 100% setidaknya pada satu jam agar sesuai dengan beban puncak.')
    return values/100.


def make_annual_profiles(base_profile, base_shape, peaks, load_shapes=None, availabilities=None):
    hours = base_profile['Jam'].tolist()
    generators = [c for c in base_profile if c not in ('Jam', 'Beban (MW)')]
    validate_shape(base_shape, hours)
    base_availability = base_profile[generators].to_numpy(dtype=float)
    if not np.isfinite(base_availability).all() or (base_availability < 0).any() or (base_availability > 1).any():
        raise ValueError('Availability tahun dasar harus berada pada rentang 0–1.')
    output = {}
    for year, peak in peaks.items():
        if not np.isfinite(peak) or peak <= 0:
            raise ValueError(f'Beban puncak tahun {year} harus hingga dan lebih besar dari nol.')
        shape = (load_shapes or {}).get(year, base_shape)
        values = validate_shape(shape, hours)
        frame = base_profile.copy()
        frame['Beban (MW)'] = float(peak)*values
        availability = (availabilities or {}).get(year)
        if availability is not None:
            if availability['Jam'].tolist() != hours:
                raise ValueError(f'Jam availability tahun {year} harus sama dengan tahun dasar.')
            # Teknologi yang baru ditambahkan mewarisi availability tahun dasar.
            for name in generators:
                if name in availability:
                    frame[name] = availability[name].to_numpy(dtype=float)
        a = frame[generators].to_numpy(dtype=float)
        if not np.isfinite(a).all() or (a < 0).any() or (a > 1).any():
            raise ValueError(f'Availability tahun {year} harus berada pada rentang 0–1.')
        output[year] = frame
    return output
