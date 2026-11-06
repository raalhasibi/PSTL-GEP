"""Ekspansi antar tahun: kapasitas kumulatif terkait, dispatch setiap tahun."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult
from solver_backend import linprog
from scipy.sparse import block_diag, coo_matrix, vstack

from model import InfeasibleModelError, OptimizationProblem, Result, build_problem, planning_profile, capital_recovery_factor
from exogenous import validate_exogenous


@dataclass
class MultiYearResult(Result):
    year_results: dict = field(default_factory=dict)
    annual_metrics: pd.DataFrame = field(default_factory=pd.DataFrame)
    capacity_plan: pd.DataFrame = field(default_factory=pd.DataFrame)
    storage_plan: pd.DataFrame = field(default_factory=pd.DataFrame)
    npv_cost: float = 0.


def build_multiyear_problem(technologies, profiles, base_year=2025, planning_years=1,
                          annual_growth=0., annual_load_factors=None, annual_profiles=None, exogenous_additions=None, **options):
    # Validasi rentang sekaligus menjaga profil sumber tetap utuh.
    planning_profile(profiles, base_year, planning_years, annual_growth)
    years = list(range(base_year+1, base_year+planning_years+1))
    exogenous = validate_exogenous(exogenous_additions, technologies, base_year, planning_years)
    names = technologies.Teknologi.tolist()
    base_capacity = technologies.get('Kapasitas tahun dasar (MW)', pd.Series(0., index=technologies.index)).to_numpy(dtype=float)
    exo_year = np.array([[exogenous.loc[(exogenous['Tahun operasi'] == year) & (exogenous.Teknologi == name),
        'Tambahan eksogen (MW)'].sum() for name in names] for year in years])
    exo_cumulative = np.cumsum(exo_year, axis=0)
    annual_investment_per_mw = technologies['Investasi (USD/kW)'].to_numpy(dtype=float)*1000*capital_recovery_factor(
        options.get('discount_rate', .08), technologies['Umur aset (tahun)'].to_numpy(dtype=float))
    if annual_profiles is not None and set(annual_profiles) != set(years):
        raise ValueError('Profil tahunan harus mencakup setiap tahun perencanaan.')
    if annual_load_factors is not None:
        if set(annual_load_factors) != set(years):
            raise ValueError('Proyeksi manual harus mencakup setiap tahun perencanaan.')
        factors = np.array([annual_load_factors[year] for year in years], dtype=float)
        if not np.isfinite(factors).all() or (factors <= 0).any():
            raise ValueError('Faktor proyeksi manual setiap tahun harus hingga dan lebih besar dari nol.')
    problems = []
    for h, year in enumerate(years, 1):
        projected = annual_profiles[year].copy() if annual_profiles is not None else planning_profile(profiles, base_year, h, annual_growth if annual_load_factors is None else 0.)
        if annual_profiles is not None and projected['Jam'].tolist() != profiles['Jam'].tolist():
            raise ValueError(f'Jam profil tahun {year} harus sama dengan tahun dasar.')
        if annual_load_factors is not None and annual_profiles is None:
            # Faktor relatif terhadap profil dasar, sehingga faktor beban
            # stokastik yang sudah diterapkan tetap ikut diperhitungkan.
            projected['Beban (MW)'] *= float(annual_load_factors[year])
        year_tech = technologies.copy()
        year_tech['Kapasitas tahun dasar (MW)'] = base_capacity+exo_cumulative[h-1]
        problems.append(build_problem(year_tech, projected, **options))
    offsets = np.r_[0, np.cumsum([len(p.c) for p in problems])]
    rate = options.get('discount_rate', .08)
    discounts = (1.+rate)**-np.arange(1, planning_years+1, dtype=float)
    c = np.concatenate([d*p.c for d, p in zip(discounts, problems)])
    eq = block_diag([p.a_eq for p in problems], format='csr')
    rhs_eq = np.concatenate([p.b_eq for p in problems])
    ub = block_diag([p.a_ub for p in problems], format='csr')
    rhs_ub = np.concatenate([p.b_ub for p in problems])
    # Variabel kapasitas tiap tahun = tambahan KUMULATIF sejak tahun dasar.
    # Kumulatif tidak boleh turun; selisih antar tahun adalah pembangunan baru.
    rows, cols, data = [], [], []
    count = 0
    for y in range(1, planning_years):
        for idx in problems[y].first_stage:
            rows.extend([count, count])
            cols.extend([int(offsets[y-1])+idx, int(offsets[y])+idx])
            data.extend([1., -1.])
            count += 1
    if count:
        links = coo_matrix((data, (rows, cols)), shape=(count, int(offsets[-1]))).tocsr()
        ub = vstack([ub, links], format='csr')
        rhs_ub = np.r_[rhs_ub, np.zeros(count)]
    bounds = [b for p in problems for b in p.bounds]
    integrality = np.concatenate([p.integrality for p in problems])

    def decode(solution):
        if not solution.success:
            if solution.status == 2:
                for year, problem in zip(years, problems):
                    try:
                        problem.run()
                    except InfeasibleModelError as exc:
                        exc.diagnosis['findings'].insert(0, f'Tahun perencanaan bermasalah: {year}. Diagnosis memakai batas total kapasitas pada tahun tersebut.')
                        raise InfeasibleModelError(f'Tidak ada solusi layak pada tahun {year}. '+str(exc), exc.diagnosis) from exc
                if not exogenous.empty:
                    capacity_rows = [{'Tahun': year, 'Teknologi': name, 'Kapasitas tahun dasar (MW)': base_capacity[i],
                        'Eksogen kumulatif (MW)': exo_cumulative[y, i],
                        'Potensi EBT (MW; 0 = tanpa batas)': float(technologies.iloc[i].get('Potensi EBT (MW)', 0.)),
                        'Batas total (MW; 0 = tanpa batas)': float(technologies.iloc[i]['Batas kapasitas (MW)'])}
                        for y, year in enumerate(years) for i, name in enumerate(names)]
                    diagnosis = {'findings': ['Setiap tahun layak bila diperiksa sendiri, tetapi jadwal pembangunan bersama tidak layak. '
                        'Kapasitas endogen yang dibutuhkan lebih awal harus tetap tersedia ketika proyek eksogen beroperasi. '
                        'Periksa batas total kapasitas, potensi EBT, dan jadwal proyek eksogen; kelayakan per tahun secara terpisah belum menjamin kelayakan seluruh periode.'],
                        'suggestions': [], 'capacity': pd.DataFrame(capacity_rows),
                        'hourly': pd.concat([pd.DataFrame({'Tahun': year, 'Jam': profiles.Jam,
                            'Beban (MW)': problems[y].b_eq[:len(profiles)]}) for y, year in enumerate(years)], ignore_index=True)}
                    raise InfeasibleModelError('Tidak ada solusi layak untuk jadwal multi tahun dengan kapasitas eksogen dan batas total saat ini.', diagnosis)
            raise RuntimeError('Optimisasi multi tahun belum menghasilkan solusi optimal: '+solution.message)
        yearly, metrics, gen_plans, store_plans = {}, [], [], []
        previous_gen, previous_storage = None, None
        for y, (year, problem, discount) in enumerate(zip(years, problems, discounts)):
            x = solution.x[offsets[y]:offsets[y+1]]
            r = problem.decode(OptimizeResult(success=True, status=0, x=x, fun=float(problem.c @ x)))
            g = r.summary
            endogenous = g['Kapasitas baru (MW)'].to_numpy().copy()
            cumulative = endogenous+exo_cumulative[y]
            before = np.zeros(len(g)) if previous_gen is None else previous_gen['Kapasitas tambahan kumulatif (MW)'].to_numpy()
            previous_endogenous = np.zeros(len(g)) if previous_gen is None else previous_gen['Endogen kumulatif (MW)'].to_numpy()
            g['Kapasitas tahun dasar (MW)'] = base_capacity
            g['Kapasitas eksogen (MW)'] = exo_year[y]
            g['Kapasitas endogen (MW)'] = np.maximum(0., endogenous-previous_endogenous)
            g['Eksogen kumulatif (MW)'] = exo_cumulative[y]
            g['Endogen kumulatif (MW)'] = endogenous
            g['Kapasitas tambahan kumulatif (MW)'] = cumulative
            g['Kapasitas awal tahun (MW)'] = g['Kapasitas tahun dasar (MW)']+before
            g['Kapasitas baru (MW)'] = np.maximum(0., cumulative-before)
            extra_annual_cost = exo_cumulative[y]*annual_investment_per_mw
            g['Investasi tahunan (USD/tahun)'] += extra_annual_cost
            g['Biaya tetap (USD/tahun)'] += extra_annual_cost
            r.annual_cost += float(extra_annual_cost.sum())
            investment_cumulative = cumulative*technologies['Investasi (USD/kW)'].to_numpy(dtype=float)*1000
            g['Investasi kumulatif (USD)'] = investment_cumulative
            g['Investasi awal (USD)'] = np.maximum(0., investment_cumulative-(0. if previous_gen is None else previous_gen['Investasi kumulatif (USD)'].to_numpy()))
            if 'Jumlah blok' in g:
                counts = g['Jumlah blok'].to_numpy().copy()
                g['Jumlah blok kumulatif'] = counts
                g['Jumlah blok'] = counts-(0 if previous_gen is None else previous_gen['Jumlah blok kumulatif'].to_numpy())
            gen_plans.append(g.assign(Tahun=year))
            previous_gen = g.copy()
            storage_investment = 0.
            if r.storage_summary is not None:
                b = r.storage_summary
                cum_power = b['Daya baru (MW)'].to_numpy().copy()
                prev_power = np.zeros(len(b)) if previous_storage is None else previous_storage['Daya tambahan kumulatif (MW)'].to_numpy()
                b['Daya tambahan kumulatif (MW)'] = cum_power
                b['Daya awal tahun (MW)'] = b['Daya tahun dasar (MW)']+prev_power
                b['Daya baru (MW)'] = np.maximum(0., cum_power-prev_power)
                b['Energi baru (MWh)'] = b['Daya baru (MW)']*b['Durasi (jam)']
                counts = b['Jumlah blok'].to_numpy().copy()
                b['Jumlah blok kumulatif'] = counts
                b['Jumlah blok'] = counts-(0 if previous_storage is None else previous_storage['Jumlah blok kumulatif'].to_numpy())
                inv = b['Investasi awal (USD)'].to_numpy().copy()
                b['Investasi kumulatif (USD)'] = inv
                b['Investasi awal (USD)'] = np.maximum(0., inv-(0. if previous_storage is None else previous_storage['Investasi kumulatif (USD)'].to_numpy()))
                storage_investment = b['Investasi awal (USD)'].sum()
                store_plans.append(b.assign(Tahun=year))
                previous_storage = b.copy()
            yearly[year] = r
            metrics.append({'Tahun': year, 'Puncak beban (MW)': r.dispatch['Beban (MW)'].max(),
                'Biaya (USD/tahun)': r.annual_cost, 'Faktor diskonto': discount,
                'Kontribusi biaya kini (USD)': discount*r.annual_cost,
                'Emisi (tCO2/tahun)': r.annual_emissions, 'Energi beban (MWh/tahun)': r.annual_energy,
                'Investasi baru (USD)': g['Investasi awal (USD)'].sum()+storage_investment})
            metrics[-1]['Tambahan eksogen (MW)'] = float(exo_year[y].sum())
            metrics[-1]['Tambahan endogen (MW)'] = float(g['Kapasitas endogen (MW)'].sum())
        last = yearly[years[-1]]
        return MultiYearResult(summary=last.summary, dispatch=last.dispatch, annual_cost=last.annual_cost,
            annual_energy=last.annual_energy, annual_emissions=last.annual_emissions,
            battery_summary=last.storage_summary, storage_dispatch=last.storage_dispatch,
            year_results=yearly, annual_metrics=pd.DataFrame(metrics), capacity_plan=pd.concat(gen_plans, ignore_index=True),
            storage_plan=pd.concat(store_plans, ignore_index=True) if store_plans else pd.DataFrame(),
            npv_cost=float(sum(d*r.annual_cost for d, r in zip(discounts, yearly.values()))))

    first_stage = [int(offsets[y])+idx for y, p in enumerate(problems) for idx in p.first_stage]
    return OptimizationProblem(c, eq, rhs_eq, ub, rhs_ub, bounds, integrality, first_stage, decode)


def solve_multiyear(technologies, profiles, **options):
    problem = build_multiyear_problem(technologies, profiles, **options)
    solution = linprog(problem.c, A_eq=problem.a_eq, b_eq=problem.b_eq, A_ub=problem.a_ub, b_ub=problem.b_ub,
        bounds=problem.bounds, integrality=problem.integrality if np.any(problem.integrality) else None,
        method='highs', options={'time_limit': 60., 'mip_rel_gap': 0.} if np.any(problem.integrality) else {'time_limit': 60.})
    return problem.decode(solution)
