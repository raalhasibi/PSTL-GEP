"""Model kapasitas satu node; semua periode berdurasi satu jam."""
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from diagnostics import diagnose

DEFAULT_BLOCK_SIZES = {'PLTU': 50., 'PLTG': 25., 'PLTS': 10., 'PLTB': 10.}
RESERVED_NAMES = {'Jam', 'Beban', 'Beban (MW)', 'Baterai', 'Baterai isi', 'Baterai keluar',
                  'Isi baterai (MW)', 'Keluar baterai (MW)', 'Energi awal jam (MWh)', 'Energi akhir jam (MWh)',
                  'Skenario', 'Model', 'Ukuran blok (MW)', 'Biaya (juta USD/tahun)', 'Emisi (ribu tCO2/tahun)',
                  'Diskonto (%)', 'Investasi awal (juta USD)', 'Investasi tahunan (juta USD/tahun)',
                  'Baterai (MW)', 'Baterai (MWh)', 'Parameter baterai', 'Pendekatan', 'Skenario ketidakpastian',
                  'Parameter penyimpanan', 'Penyimpanan per teknologi', 'Penyimpanan (MW)', 'Penyimpanan (MWh)',
                  'Parameter tidak pasti', 'Kapasitas tahun dasar (MW)', 'Kapasitas baru (MW)',
                  'Daya tahun dasar (MW)', 'Daya baru (MW)', 'Tahun dasar', 'Tahun akhir',
                  'Periode perencanaan (tahun)', 'Pertumbuhan beban tahunan (%)',
                  'Tahun', 'Tahun hasil', 'Nilai kini biaya periode (juta USD)',
                  'Kapasitas eksogen (MW)', 'Kapasitas endogen (MW)', 'Eksogen kumulatif (MW)', 'Endogen kumulatif (MW)'}


def capital_recovery_factor(rate, lifetime):
    """CRF tahunan; rate berupa pecahan (0.08 = 8%), umur dalam tahun."""
    lifetime = np.asarray(lifetime, dtype=float)
    if not np.isfinite(rate) or rate < 0 or not np.isfinite(lifetime).all() or (lifetime <= 0).any():
        raise ValueError('Tingkat diskonto harus tidak negatif dan umur aset harus lebih besar dari nol.')
    if rate == 0:
        return 1/lifetime
    return rate / -np.expm1(-lifetime*np.log1p(rate))


def planning_profile(profiles, base_year, planning_years, annual_growth=0.):
    """Profil tahun akhir dari beban tahun dasar; annual_growth berupa pecahan.

    Ini proyeksi untuk optimisasi satu tahun akhir, bukan ekspansi multiyear.
    Profil sumber tidak dimutasi agar rerun tidak menggandakan pertumbuhan.
    """
    if (isinstance(base_year, bool) or not isinstance(base_year, (int, np.integer))
            or not 1900 <= base_year <= 2200):
        raise ValueError('Tahun dasar harus bilangan bulat antara 1900 dan 2200.')
    if (isinstance(planning_years, bool) or not isinstance(planning_years, (int, np.integer))
            or not 1 <= planning_years <= 50):
        raise ValueError('Periode perencanaan harus bilangan bulat antara 1 dan 50 tahun.')
    if not np.isfinite(annual_growth) or annual_growth <= -1:
        raise ValueError('Pertumbuhan beban harus hingga dan lebih besar dari -100%.')
    with np.errstate(over='ignore', invalid='ignore'):
        factor = np.power(1.+annual_growth, planning_years)
        demand = profiles['Beban (MW)'].to_numpy(dtype=float)*factor
    if not np.isfinite(demand).all() or (demand < 0).any() or demand.sum() <= 0:
        raise ValueError('Proyeksi beban tahun akhir harus hingga, tidak negatif, dan memiliki total positif.')
    projected = profiles.copy()
    projected['Beban (MW)'] = demand
    return projected


def validate_names(names):
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError('Nama teknologi tidak boleh kosong.')
    normalized = [name.strip().casefold() for name in names]
    if len(set(normalized)) != len(names):
        raise ValueError('Nama teknologi harus unik (tanpa membedakan huruf besar/kecil).')
    if set(normalized) & {name.casefold() for name in RESERVED_NAMES}:
        raise ValueError('Nama teknologi menggunakan nama kolom sistem atau baterai yang dicadangkan.')


def add_technology(technologies, profiles, name, investment, fixed_om, variable,
                   emissions, maximum, lifetime, block_mw, availability, existing_mw=0.):
    """Tambahkan teknologi dan profil secara atomik; input asli tidak diubah."""
    name = name.strip()
    validate_names(technologies['Teknologi'].tolist()+[name])
    values = np.array([investment, fixed_om, variable, emissions, maximum, lifetime, block_mw, existing_mw], dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or lifetime <= 0 or block_mw <= 0:
        raise ValueError('Biaya, emisi, dan batas kapasitas harus tidak negatif; umur dan ukuran blok harus positif.')
    if maximum > 0 and existing_mw > maximum:
        raise ValueError('Kapasitas tahun dasar tidak boleh melebihi batas kapasitas total.')
    availability = np.broadcast_to(np.asarray(availability, dtype=float), (len(profiles),))
    if not np.isfinite(availability).all() or (availability < 0).any() or (availability > 1).any():
        raise ValueError('Ketersediaan harus berada antara 0 dan 1.')
    row = {'Teknologi': name, 'O&M tetap (USD/kW/tahun)': fixed_om,
           'Biaya variabel (USD/MWh)': variable, 'Emisi (tCO2/MWh)': emissions,
           'Batas kapasitas (MW)': maximum, 'Investasi (USD/kW)': investment,
           'Umur aset (tahun)': lifetime, 'Ukuran blok (MW)': block_mw,
           'Kapasitas tahun dasar (MW)': existing_mw}
    updated = pd.concat([technologies, pd.DataFrame([row])], ignore_index=True)
    updated_profiles = profiles.copy()
    updated_profiles[name] = availability
    return updated, updated_profiles


class InfeasibleModelError(ValueError):
    def __init__(self, message, diagnosis):
        super().__init__(message)
        self.diagnosis = diagnosis


def example_inputs(peak_mw=100.0):
    demand = np.array([.60, .56, .53, .52, .54, .60, .68, .75, .81, .85, .87, .88,
                       .86, .85, .87, .90, .94, 1., .98, .92, .85, .78, .71, .65]) * peak_mw
    solar = np.maximum(0, np.sin((np.arange(24) - 6) * np.pi / 12))
    solar[18:] = 0
    wind = np.array([.50, .52, .55, .57, .55, .50, .45, .40, .35, .32, .30, .28,
                     .30, .32, .35, .38, .42, .45, .48, .50, .52, .53, .52, .50])
    technologies = pd.DataFrame({
        'Teknologi': ['PLTU', 'PLTG', 'PLTS', 'PLTB'],
        'O&M tetap (USD/kW/tahun)': [40., 20., 12., 30.],
        'Biaya variabel (USD/MWh)': [35., 85., 0., 0.],
        'Emisi (tCO2/MWh)': [.95, .40, 0., 0.],
        'Batas kapasitas (MW)': [0., 0., 0., 0.],
        'Investasi (USD/kW)': [1800., 700., 600., 1100.],
        'Umur aset (tahun)': [30., 25., 25., 25.],
        'Ukuran blok (MW)': [50., 25., 10., 10.],
        'Kapasitas tahun dasar (MW)': [0., 0., 0., 0.],
    })
    profiles = pd.DataFrame({'Jam': np.arange(24), 'Beban (MW)': demand,
                             'PLTU': np.ones(24), 'PLTG': np.ones(24),
                             'PLTS': solar, 'PLTB': wind})
    return technologies, profiles


@dataclass
class BatteryConfig:
    block_mw: float = 10.
    duration_hours: float = 4.
    max_power_mw: float = 200.
    power_cost: float = 10.  # O&M tetap USD/kW/tahun
    energy_cost: float = 2.  # O&M tetap USD/kWh/tahun
    round_trip_efficiency: float = .90
    discharge_cost: float = 2.  # USD/MWh keluar ke node
    investment_power: float = 300.  # USD/kW
    investment_energy: float = 150.  # USD/kWh
    lifetime: float = 15.  # tahun
    existing_power_mw: float = 0.  # energi tahun dasar = daya × durasi

    def validate(self):
        values = np.array(list(vars(self).values()), dtype=float)
        if not np.isfinite(values).all():
            raise ValueError('Parameter baterai harus berupa angka hingga.')
        if self.block_mw <= 0 or self.duration_hours <= 0:
            raise ValueError('Daya blok dan durasi baterai harus lebih besar dari nol.')
        if min(self.max_power_mw, self.power_cost, self.energy_cost, self.discharge_cost) < 0:
            raise ValueError('Batas daya dan biaya baterai harus tidak negatif.')
        if not 0 < self.round_trip_efficiency <= 1:
            raise ValueError('Efisiensi round-trip baterai harus lebih besar dari 0 dan maksimum 1.')
        if min(self.investment_power, self.investment_energy) < 0 or self.lifetime <= 0:
            raise ValueError('Investasi baterai harus tidak negatif dan umur baterai harus positif.')
        if not 0 <= self.existing_power_mw <= self.max_power_mw:
            raise ValueError('Daya tahun dasar penyimpanan harus tidak negatif dan tidak melebihi batas daya total.')


@dataclass
class Result:
    summary: pd.DataFrame
    dispatch: pd.DataFrame
    annual_cost: float
    annual_energy: float
    annual_emissions: float
    battery_summary: pd.DataFrame | None = None
    storage_dispatch: dict = field(default_factory=dict)

    @property
    def storage_summary(self):
        return self.battery_summary


@dataclass
class OptimizationProblem:
    c: np.ndarray
    a_eq: np.ndarray
    b_eq: np.ndarray
    a_ub: np.ndarray
    b_ub: np.ndarray
    bounds: list
    integrality: np.ndarray
    first_stage: list
    decode: Callable

    def run(self):
        integer = bool(np.any(self.integrality))
        solution = linprog(self.c, A_ub=self.a_ub, b_ub=self.b_ub, A_eq=self.a_eq, b_eq=self.b_eq,
                           bounds=self.bounds, integrality=self.integrality if integer else None,
                           options={'mip_rel_gap': 0.0} if integer else None, method='highs')
        return self.decode(solution)


def build_problem(technologies, profiles, carbon_price=0., emissions_limit=None, days=365,
          capacity_model='continuous', block_sizes=None, battery=None, discount_rate=.08, storages=None):
    """Minimalkan investasi tahunan (CRF) + O&M tetap + operasi + karbon.

    K dalam MW; p dalam MW; investasi USD/kW ditahunkan menurut umur dan
    discount_rate, lalu dijumlah O&M tetap USD/kW/tahun dan dikali 1.000.
    days adalah bobot setiap jam contoh dalam satu tahun.
    Variabel kapasitas adalah penambahan baru; K_total = K_dasar + K_baru.
    Pada model integer K_baru = B*N. Batas positif adalah batas TOTAL;
    nilai nol berarti tanpa batas kapasitas pembangkit.
    block_sizes memetakan nama teknologi ke ukuran blok dalam MW.
    battery: BatteryConfig default opsional; storages: peta nama -> BatteryConfig
    untuk jenis penyimpanan tambahan, hanya untuk model integer. Siklus energi
    harian tertutup; variabel biner mencegah charge/discharge bersamaan.
    """
    names = technologies.iloc[:, 0].tolist()
    n, t = len(names), len(profiles)
    if not n or not t or len(set(names)) != n:
        raise ValueError('Teknologi harus unik dan data tidak boleh kosong.')
    validate_names(names)
    required = ['O&M tetap (USD/kW/tahun)', 'Biaya variabel (USD/MWh)', 'Emisi (tCO2/MWh)',
                'Batas kapasitas (MW)', 'Investasi (USD/kW)', 'Umur aset (tahun)', 'Ukuran blok (MW)']
    if not set(required).issubset(technologies.columns):
        raise ValueError('Parameter teknologi belum lengkap: diperlukan investasi, O&M, umur aset, dan ukuran blok.')
    params = technologies[required].to_numpy(dtype=float)
    if not np.isfinite(params).all() or (params < 0).any():
        raise ValueError('Parameter pembangkit harus berupa angka hingga dan tidak negatif.')
    fixed_om, variable, emissions, maximum, investment, lifetime, default_blocks = params.T
    existing = technologies.get('Kapasitas tahun dasar (MW)', pd.Series(0., index=technologies.index)).to_numpy(dtype=float)
    if not np.isfinite(existing).all() or (existing < 0).any() or ((maximum > 0) & (existing > maximum)).any():
        raise ValueError('Kapasitas tahun dasar harus tidak negatif, hingga, dan tidak melebihi batas kapasitas total.')
    constant_cost = float(existing @ fixed_om * 1000)
    crf = capital_recovery_factor(discount_rate, lifetime)
    if (default_blocks <= 0).any():
        raise ValueError('Ukuran blok harus lebih besar dari nol.')
    fixed = fixed_om+investment*crf
    if not set(names+['Jam', 'Beban (MW)']).issubset(profiles.columns):
        raise ValueError('Profil per jam harus tersedia untuk setiap teknologi, beserta jam dan beban.')
    demand = profiles['Beban (MW)'].to_numpy(dtype=float)
    availability = profiles[names].to_numpy(dtype=float).T
    if not np.isfinite(demand).all() or (demand < 0).any() or demand.sum() <= 0:
        raise ValueError('Beban harus tidak negatif, hingga, dan memiliki total positif.')
    if not np.isfinite(availability).all() or (availability < 0).any() or (availability > 1).any():
        raise ValueError('Ketersediaan pembangkit harus berada antara 0 dan 1.')
    if not np.isfinite([carbon_price, days]).all() or carbon_price < 0 or days <= 0:
        raise ValueError('Harga karbon harus tidak negatif dan bobot hari harus positif.')
    if emissions_limit is not None and (not np.isfinite(emissions_limit) or emissions_limit < 0):
        raise ValueError('Batas emisi harus berupa angka hingga dan tidak negatif.')
    if capacity_model not in ('continuous', 'integer'):
        raise ValueError('Pilihan model harus continuous atau integer.')
    integer = capacity_model == 'integer'
    storage_configs = dict(storages or {})
    if battery is not None:
        if 'Baterai' in storage_configs:
            raise ValueError('Baterai default tidak boleh diberikan dua kali.')
        storage_configs = {'Baterai': battery, **storage_configs}
    if storage_configs:
        if not integer:
            raise ValueError('Penyimpanan tersedia pada model blok integer.')
        storage_names = list(storage_configs)
        for name in storage_names:
            if not isinstance(name, str) or not name.strip():
                raise ValueError('Nama penyimpanan tidak boleh kosong.')
        if len({name.strip().casefold() for name in storage_names}) != len(storage_names):
            raise ValueError('Nama penyimpanan harus unik.')
        validate_names([name for name in storage_names if name != 'Baterai'])
        if {name.strip().casefold() for name in storage_names} & {name.strip().casefold() for name in names}:
            raise ValueError('Nama penyimpanan tidak boleh sama dengan nama pembangkit.')
        for config in storage_configs.values():
            config.validate()
        derived = {f'{name} · {suffix}' for name in storage_names
                   for suffix in ['Isi (MW)', 'Keluar (MW)', 'Energi awal (MWh)', 'Energi akhir (MWh)']}
        if derived & set(names):
            raise ValueError('Nama pembangkit bertabrakan dengan nama kolom operasi penyimpanan.')
    scale = np.ones(n)
    if integer:
        sizes = dict(zip(names, default_blocks)) if block_sizes is None else block_sizes
        try:
            scale = np.array([sizes[name] for name in names], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Ukuran blok harus tersedia untuk setiap teknologi.') from exc
        if not np.isfinite(scale).all() or (scale <= 0).any():
            raise ValueError('Ukuran blok harus berupa angka hingga dan lebih besar dari nol.')
    # x = [K_i (kontinu) atau N_i (integer), lalu dispatch p_i,t].
    c = np.r_[fixed * 1000 * scale, np.repeat(variable + carbon_price * emissions, t) * days]
    a_eq = np.zeros((t, n + n*t))
    a_ub = np.zeros((n*t, n + n*t))
    for i in range(n):
        for h in range(t):
            j = n + i*t + h
            a_eq[h, j] = 1
            a_ub[i*t+h, i] = -availability[i, h]*scale[i]
            a_ub[i*t+h, j] = 1
    b_ub = (availability*existing[:, None]).ravel()
    remaining = np.where(maximum > 0, maximum-existing, np.inf)
    capacity_upper = np.floor(remaining/scale) if integer else remaining
    bounds = [(0, float(m) if np.isfinite(m) else None) for m in capacity_upper] + [(0, None)]*(n*t)
    integrality = np.r_[np.ones(n) if integer else np.zeros(n), np.zeros(n*t)]
    demand_rhs = demand.copy()
    storage_specs = []
    for storage_name, config in storage_configs.items():
        battery = config
        # Tambahan: N_b, charge[t], discharge[t], SOC[t+1], mode_charge[t].
        base = len(c)
        ub_start = len(b_ub)
        nb = base
        charge = base + 1 + np.arange(t)
        discharge = base + 1 + t + np.arange(t)
        soc = base + 1 + 2*t + np.arange(t+1)
        mode = base + 2 + 3*t + np.arange(t)
        extra = 4*t+2
        total = base+extra
        max_blocks = np.floor((battery.max_power_mw-battery.existing_power_mw)/battery.block_mw)
        max_power = battery.existing_power_mw+max_blocks*battery.block_mw
        existing_energy = battery.existing_power_mw*battery.duration_hours
        constant_cost += 1000*(battery.existing_power_mw*battery.power_cost+existing_energy*battery.energy_cost)
        block_energy = battery.block_mw*battery.duration_hours
        eta = np.sqrt(battery.round_trip_efficiency)
        battery_crf = float(capital_recovery_factor(discount_rate, battery.lifetime))
        c = np.r_[c, np.zeros(extra)]
        c[nb] = 1000*(battery.block_mw*(battery.power_cost+battery.investment_power*battery_crf)
                      + block_energy*(battery.energy_cost+battery.investment_energy*battery_crf))
        c[discharge] = battery.discharge_cost*days
        bounds += [(0, float(max_blocks))] + [(0, None)]*(3*t+1) + [(0, 1)]*t
        integrality = np.r_[integrality, 1, np.zeros(3*t+1), np.ones(t)]
        a_eq = np.pad(a_eq, ((0, 0), (0, extra)))
        a_ub = np.pad(a_ub, ((0, 0), (0, extra)))
        eq = np.zeros((t+1, total))
        ub = np.zeros((5*t+1, total))
        rhs = np.zeros(5*t+1)
        for h in range(t):
            a_eq[h, charge[h]] = -1
            a_eq[h, discharge[h]] = 1
            eq[h, soc[h+1]] = 1
            eq[h, soc[h]] = -1
            eq[h, charge[h]] = -eta
            eq[h, discharge[h]] = 1/eta
            # Limites daya sesuai kapasitas yang dibangun.
            ub[5*h, charge[h]] = 1
            ub[5*h, nb] = -battery.block_mw
            ub[5*h+1, discharge[h]] = 1
            ub[5*h+1, nb] = -battery.block_mw
            ub[5*h+2, soc[h]] = 1
            ub[5*h+2, nb] = -block_energy
            rhs[5*h] = battery.existing_power_mw
            rhs[5*h+1] = battery.existing_power_mw
            rhs[5*h+2] = existing_energy
            # Biner mode operasi memakai batas daya tetap (big-M).
            ub[5*h+3, charge[h]] = 1
            ub[5*h+3, mode[h]] = -max_power
            ub[5*h+4, discharge[h]] = 1
            ub[5*h+4, mode[h]] = max_power
            rhs[5*h+4] = max_power
        ub[-1, soc[-1]] = 1
        ub[-1, nb] = -block_energy
        rhs[-1] = existing_energy
        eq[-1, soc[-1]] = 1
        eq[-1, soc[0]] = -1
        a_eq = np.vstack([a_eq, eq])
        demand_rhs = np.r_[demand_rhs, np.zeros(t+1)]
        a_ub = np.vstack([a_ub, ub])
        b_ub = np.r_[b_ub, rhs]
        storage_specs.append(dict(name=storage_name, config=config, nb=nb, charge=charge,
                                  discharge=discharge, soc=soc, mode=mode, ub_start=ub_start,
                                  crf=battery_crf))
    if emissions_limit is not None:
        row = np.zeros(len(c))
        row[n:n+n*t] = np.repeat(emissions, t)*days
        a_ub = np.vstack([a_ub, row])
        b_ub = np.r_[b_ub, emissions_limit]

    def decode(solution):
        if not solution.success:
            if solution.status == 2:
                context = dict(n=n, t=t, names=names, scale=scale, demand=demand, available=availability,
                               maximum=maximum, existing=existing, battery=None, hours=profiles['Jam'].to_numpy(), days=days,
                               emissions=emissions, emissions_limit=emissions_limit, integer=integer)
                context['storage_specs'] = storage_specs
                diagnosis = diagnose(a_eq, demand_rhs, a_ub, b_ub, bounds, integrality, context)
                raise InfeasibleModelError('Tidak ada solusi layak. Periksa batas kapasitas, ketersediaan per jam, '
                                 'dan batas emisi. Pada model integer, periksa juga ukuran blok. '
                                 'Semua beban harus terpenuhi pada setiap jam.', diagnosis)
            raise RuntimeError(f'Optimasi gagal: {solution.message}')
        added = np.maximum(solution.x[:n]*scale, 0.)
        capacity = existing+added
        power = solution.x[n:n+n*t].reshape(n, t)
        energy = power.sum(axis=1)*days
        summary = pd.DataFrame({'Teknologi': names, 'Kapasitas (MW)': capacity,
                                'Kapasitas tahun dasar (MW)': existing,
                                'Kapasitas baru (MW)': added,
                                'Produksi (MWh/tahun)': energy,
                                'Biaya tetap (USD/tahun)': (added*investment*crf+capacity*fixed_om)*1000,
                                'Biaya operasi (USD/tahun)': energy*variable,
                                'Biaya karbon (USD/tahun)': energy*emissions*carbon_price,
                                'Emisi (tCO2/tahun)': energy*emissions})
        summary['Investasi awal (USD)'] = added*1000*investment
        summary['Investasi tahunan (USD/tahun)'] = added*1000*investment*crf
        summary['O&M tetap (USD/tahun)'] = capacity*1000*fixed_om
        summary['CRF (1/tahun)'] = crf
        if integer:
            summary['Ukuran blok (MW)'] = scale
            summary['Jumlah blok'] = np.rint(solution.x[:n]).astype(int)
        dispatch = pd.DataFrame(power.T, columns=names)
        dispatch.insert(0, 'Jam', profiles['Jam'].to_numpy())
        dispatch['Beban (MW)'] = demand
        storage_rows, storage_dispatch = [], {}
        for spec in storage_specs:
            storage_name, battery = spec['name'], spec['config']
            nb, charge, discharge, soc = [spec[key] for key in ['nb', 'charge', 'discharge', 'soc']]
            battery_crf = spec['crf']
            blocks = int(round(solution.x[nb]))
            added_power = blocks*battery.block_mw
            battery_power = battery.existing_power_mw+added_power
            battery_energy = battery_power*battery.duration_hours
            charged = solution.x[charge]
            discharged = solution.x[discharge]
            levels = solution.x[soc]
            battery_investment = 1000*added_power*(battery.investment_power + battery.duration_hours*battery.investment_energy)
            battery_om = 1000*(battery_power*battery.power_cost + battery_energy*battery.energy_cost)
            operation = pd.DataFrame({'Jam': profiles['Jam'].to_numpy(), 'Isi baterai (MW)': charged,
                                      'Keluar baterai (MW)': discharged, 'Energi awal jam (MWh)': levels[:-1],
                                      'Energi akhir jam (MWh)': levels[1:]})
            storage_dispatch[storage_name] = operation
            for suffix, values in [('Isi (MW)', charged), ('Keluar (MW)', discharged),
                                   ('Energi awal (MWh)', levels[:-1]), ('Energi akhir (MWh)', levels[1:])]:
                dispatch[f'{storage_name} · {suffix}'] = values
            storage_rows.append({
                'Teknologi': storage_name,
                'Daya blok (MW)': battery.block_mw,
                'Efisiensi round-trip (0–1)': battery.round_trip_efficiency,
                'Jumlah blok': blocks, 'Daya (MW)': battery_power, 'Energi (MWh)': battery_energy,
                'Daya tahun dasar (MW)': battery.existing_power_mw,
                'Daya baru (MW)': added_power,
                'Energi tahun dasar (MWh)': battery.existing_power_mw*battery.duration_hours,
                'Energi baru (MWh)': added_power*battery.duration_hours,
                'Durasi (jam)': battery.duration_hours,
                'Biaya tetap (USD/tahun)': battery_investment*battery_crf+battery_om,
                'Investasi awal (USD)': battery_investment,
                'Investasi tahunan (USD/tahun)': battery_investment*battery_crf,
                'O&M tetap (USD/tahun)': battery_om,
                'CRF (1/tahun)': battery_crf,
                'Biaya operasi (USD/tahun)': discharged.sum()*days*battery.discharge_cost,
                'Energi masuk (MWh/tahun)': charged.sum()*days,
                'Energi keluar (MWh/tahun)': discharged.sum()*days,
                'Rugi energi (MWh/tahun)': (charged.sum()-discharged.sum())*days,
            })
        battery_summary = pd.DataFrame(storage_rows) if storage_rows else None
        if storage_rows:
            for column in ['Isi baterai (MW)', 'Keluar baterai (MW)', 'Energi awal jam (MWh)', 'Energi akhir jam (MWh)']:
                dispatch[column] = sum(operation[column].to_numpy() for operation in storage_dispatch.values())
        return Result(summary, dispatch, float(solution.fun)+constant_cost, float(demand.sum()*days),
                      float(energy @ emissions), battery_summary, storage_dispatch)

    first_stage = list(range(n)) + [spec['nb'] for spec in storage_specs]
    return OptimizationProblem(c, a_eq, demand_rhs, a_ub, b_ub, bounds, integrality, first_stage, decode)


def solve(technologies, profiles, carbon_price=0., emissions_limit=None, days=365,
          capacity_model='continuous', block_sizes=None, battery=None, discount_rate=.08, storages=None):
    return build_problem(technologies, profiles, carbon_price, emissions_limit, days,
                         capacity_model, block_sizes, battery, discount_rate, storages).run()
