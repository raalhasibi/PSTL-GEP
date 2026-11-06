"""Jadwal pembangunan pembangkit yang ditetapkan pengguna."""
import numpy as np
import pandas as pd


EXOGENOUS_COLUMNS = ['Tahun operasi', 'Teknologi', 'Tambahan eksogen (MW)']


def empty_exogenous():
    return pd.DataFrame({'Tahun operasi': pd.Series(dtype=int), 'Teknologi': pd.Series(dtype=str),
                         'Tambahan eksogen (MW)': pd.Series(dtype=float)}).reset_index(drop=True)


def validate_exogenous(table, technologies, base_year, planning_years):
    if table is None or table.empty:
        return empty_exogenous()
    if not set(EXOGENOUS_COLUMNS).issubset(table.columns):
        raise ValueError('Tabel kapasitas eksogen memerlukan Tahun operasi, Teknologi, dan Tambahan eksogen (MW).')
    out = table[EXOGENOUS_COLUMNS].copy().reset_index(drop=True)
    for i, row in out.iterrows():
        try:
            year, amount = float(row['Tahun operasi']), float(row['Tambahan eksogen (MW)'])
        except (TypeError, ValueError):
            raise ValueError(f'Kapasitas eksogen baris {i+1}: tahun dan kapasitas wajib berupa angka.') from None
        if not np.isfinite(year) or not year.is_integer() or not base_year < year <= base_year+planning_years:
            raise ValueError(f'Kapasitas eksogen baris {i+1}: tahun operasi harus antara {base_year+1} dan {base_year+planning_years}.')
        if row['Teknologi'] not in technologies.Teknologi.tolist():
            raise ValueError(f'Kapasitas eksogen baris {i+1}: teknologi {row["Teknologi"]} tidak ditemukan pada tabel pembangkit.')
        if not np.isfinite(amount) or amount < 0:
            raise ValueError(f'Kapasitas eksogen baris {i+1}: tambahan MW harus hingga dan tidak negatif.')
        out.at[i, 'Tahun operasi'] = int(year)
        out.at[i, 'Tambahan eksogen (MW)'] = amount
    out['Tahun operasi'] = out['Tahun operasi'].astype(int)
    out['Tambahan eksogen (MW)'] = out['Tambahan eksogen (MW)'].astype(float)
    # Beberapa proyek teknologi/tahun yang sama dijumlahkan, bukan saling menimpa.
    for _, row in technologies.iterrows():
        total = out.loc[out.Teknologi == row.Teknologi, 'Tambahan eksogen (MW)'].sum()
        existing = float(row.get('Kapasitas tahun dasar (MW)', 0.))
        maximum = float(row['Batas kapasitas (MW)'])
        potential = float(row.get('Potensi EBT (MW)', 0.))
        if not np.isfinite(potential) or potential < 0:
            raise ValueError(f'Potensi EBT {row.Teknologi} harus hingga dan tidak negatif.')
        if potential > 0 and existing+total > potential+1e-8:
            raise ValueError(f'Kapasitas tahun dasar + tambahan eksogen {row.Teknologi} ({existing+total:g} MW) '
                             f'melebihi potensi EBT {potential:g} MW. Periksa data potensi atau jadwal eksogen.')
        if maximum > 0 and existing+total > maximum+1e-8:
            raise ValueError(f'Kapasitas tahun dasar + tambahan eksogen {row.Teknologi} ({existing+total:g} MW) '
                             f'melebihi batas total {maximum:g} MW. Ubah batas kapasitas atau jadwal eksogen.')
    return out
