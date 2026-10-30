"""Model dua tahap: kapasitas bersama, dispatch berbeda pada tiap skenario."""
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult, linprog
from scipy.sparse import block_diag, coo_matrix, vstack

from model import InfeasibleModelError, Result, build_problem

MAX_SCENARIOS = 50


def uncertainty_catalog(technologies, carbon_price=0., discount_rate=.08, emissions_limit=None,
                        battery=None, storages=None, **unused):
    """Parameter operasi/ekonomi yang boleh berubah; desain fisik tahap pertama tetap."""
    catalog = {}

    def add(label, scope, field=None, target=None, base=1., scale=1., positive=False, maximum=None, factor=False):
        catalog[label] = dict(scope=scope, field=field, target=target, base=float(base), scale=scale,
                              positive=positive, maximum=maximum, factor=factor)

    add('Faktor beban', 'load', positive=True, factor=True)
    add('Harga karbon (USD/tCO2)', 'global', 'carbon_price', base=carbon_price)
    add('Tingkat diskonto (%)', 'global', 'discount_rate', base=discount_rate*100, scale=.01, maximum=100.)
    if emissions_limit is not None:
        add('Batas emisi (tCO2/tahun)', 'global', 'emissions_limit', base=emissions_limit)
    for _, row in technologies.iterrows():
        name = row['Teknologi']
        add(f'Faktor {name}', 'availability', target=name, factor=True)
        for column in ['Investasi (USD/kW)', 'O&M tetap (USD/kW/tahun)', 'Biaya variabel (USD/MWh)',
                       'Emisi (tCO2/MWh)', 'Umur aset (tahun)']:
            add(f'Pembangkit {name} · {column}', 'generator', column, name, row[column],
                positive=column == 'Umur aset (tahun)')
    configs = {'Baterai': battery} if battery is not None else {}
    configs.update(storages or {})
    for name, config in configs.items():
        fields = [('Investasi daya (USD/kW)', 'investment_power'), ('Investasi energi (USD/kWh)', 'investment_energy'),
                  ('O&M daya (USD/kW/tahun)', 'power_cost'), ('O&M energi (USD/kWh/tahun)', 'energy_cost'),
                  ('Biaya operasi (USD/MWh keluar)', 'discharge_cost'), ('Umur aset (tahun)', 'lifetime')]
        for label, attr in fields:
            add(f'Penyimpanan {name} · {label}', 'storage', attr, name, getattr(config, attr), positive=attr == 'lifetime')
        add(f'Penyimpanan {name} · Efisiensi round-trip (%)', 'storage', 'round_trip_efficiency', name,
            config.round_trip_efficiency*100, scale=.01, positive=True, maximum=100.)
    return catalog


def resize_scenarios(table, count, catalog):
    """Pertahankan baris lama; saat jumlah berubah probabilitas disetel merata."""
    if not isinstance(count, (int, np.integer)) or not 1 <= count <= MAX_SCENARIOS:
        raise ValueError(f'Jumlah skenario harus antara 1 dan {MAX_SCENARIOS}.')
    out = table.copy().reset_index(drop=True)
    changed = len(out) != count
    out = out.iloc[:count].copy()
    existing = {str(name).strip().casefold() for name in out['Skenario']}
    for index in range(len(out), count):
        number = index+1
        while f'skenario {number}' in existing:
            number += 1
        label = f'Skenario {number}'
        existing.add(label.casefold())
        row = {'Skenario': label, 'Probabilitas': 1/count}
        for column in out.columns:
            if column in catalog:
                row[column] = catalog[column]['base']
        out = pd.concat([out, pd.DataFrame([row])], ignore_index=True)
    for label, spec in catalog.items():
        if label not in out:
            out[label] = spec['base']
    if changed:
        out['Probabilitas'] = 1/count
    return out, changed


def example_scenarios(names):
    table = pd.DataFrame({'Skenario': ['Ringan', 'Normal', 'Berat'], 'Probabilitas': [.25, .50, .25],
                          'Faktor beban': [.90, 1., 1.10]})
    for name in names:
        table[f'Faktor {name}'] = [1.1, 1., .8] if name == 'PLTS' else ([1.1, 1., .7] if name == 'PLTB' else [1., 1., 1.])
    return table


class StochasticInfeasibleError(ValueError):
    def __init__(self, failures):
        super().__init__('Tidak ada solusi layak pada model stokastik. Skenario bermasalah: '+', '.join(failures)+'.')
        self.scenario_diagnoses = failures


@dataclass
class StochasticResult(Result):
    scenario_results: dict = field(default_factory=dict)
    scenario_metrics: pd.DataFrame = field(default_factory=pd.DataFrame)
    scenario_inputs: pd.DataFrame = field(default_factory=pd.DataFrame)
    uncertainty_parameters: list = field(default_factory=list)


def solve_stochastic(technologies, profiles, scenarios, uncertainty_parameters=None, **kwargs):
    names = technologies['Teknologi'].tolist()
    catalog = uncertainty_catalog(technologies, **kwargs)
    selected = [c for c in scenarios.columns if c not in ['Skenario', 'Probabilitas']] if uncertainty_parameters is None else list(uncertainty_parameters)
    if len(set(selected)) != len(selected) or any(column not in catalog for column in selected):
        raise ValueError('Pilihan parameter ketidakpastian tidak dikenal atau berulang.')
    required = ['Skenario', 'Probabilitas']+selected
    if not set(required).issubset(scenarios.columns) or not 1 <= len(scenarios) <= MAX_SCENARIOS:
        raise ValueError(f'Tabel stokastik harus lengkap dan berisi 1–{MAX_SCENARIOS} skenario.')
    scenarios = scenarios.copy()
    for column in required[1:]:
        scenarios[column] = scenarios[column].astype(float)
    labels = scenarios['Skenario'].tolist()
    if any(not isinstance(s, str) or not s.strip() for s in labels) or len(set(s.strip().casefold() for s in labels)) != len(labels):
        raise ValueError('Nama skenario stokastik harus terisi dan unik.')
    parameters = scenarios[required[1:]].to_numpy(dtype=float)
    if not np.isfinite(parameters).all() or (parameters < 0).any():
        raise ValueError('Probabilitas dan faktor skenario harus berupa angka hingga dan tidak negatif.')
    probabilities = scenarios.Probabilitas.to_numpy(dtype=float)
    if (probabilities <= 0).any() or not np.isclose(probabilities.sum(), 1., rtol=0., atol=1e-8):
        raise ValueError('Setiap probabilitas harus lebih besar dari nol dan jumlahnya harus tepat 1. Hapus baris yang tidak digunakan.')
    for column in selected:
        spec = catalog[column]
        if spec['positive'] and (scenarios[column] <= 0).any():
            raise ValueError(f'{column} harus lebih besar dari nol.')
        if spec['maximum'] is not None and (scenarios[column] > spec['maximum']).any():
            raise ValueError(f'{column} tidak boleh lebih dari {spec["maximum"]:g}.')
    # Validasi profil dasar sebelum clipping hasil pengalian faktor skenario.
    build_problem(technologies, profiles, **kwargs)
    problems = []
    for _, row in scenarios.iterrows():
        scenario_profile = profiles.copy()
        scenario_tech = technologies.copy()
        scenario_options = dict(kwargs)
        scenario_options['storages'] = dict(kwargs.get('storages') or {})
        for column in selected:
            spec, value = catalog[column], float(row[column])*catalog[column]['scale']
            if spec['scope'] == 'load':
                scenario_profile['Beban (MW)'] = profiles['Beban (MW)']*value
            elif spec['scope'] == 'availability':
                name = spec['target']
                scenario_profile[name] = np.clip(profiles[name].to_numpy(dtype=float)*value, 0., 1.)
            elif spec['scope'] == 'global':
                scenario_options[spec['field']] = value
            elif spec['scope'] == 'generator':
                scenario_tech.loc[scenario_tech.Teknologi == spec['target'], spec['field']] = value
            elif spec['scope'] == 'storage':
                name = spec['target']
                if name == 'Baterai' and kwargs.get('battery') is not None:
                    scenario_options['battery'] = replace(scenario_options['battery'], **{spec['field']: value})
                else:
                    scenario_options['storages'][name] = replace(scenario_options['storages'][name], **{spec['field']: value})
        problems.append(build_problem(scenario_tech, scenario_profile, **scenario_options))

    # Salinan variabel kapasitas ditautkan antar skenario (non-anticipativity).
    # Bobot probabilitas pada semua biaya membuat biaya tetap terhitung sekali.
    sizes = [len(p.c) for p in problems]
    offsets = np.r_[0, np.cumsum(sizes)]
    objective = np.concatenate([prob*p.c for prob, p in zip(probabilities, problems)])
    eq = block_diag([p.a_eq for p in problems], format='csr')
    rhs_eq = np.concatenate([p.b_eq for p in problems])
    ub = block_diag([p.a_ub for p in problems], format='csr')
    rhs_ub = np.concatenate([p.b_ub for p in problems])
    rows, columns, values = [], [], []
    count = 0
    for s in range(1, len(problems)):
        for idx in problems[0].first_stage:
            rows.extend([count, count])
            columns.extend([idx, int(offsets[s])+idx])
            values.extend([1., -1.])
            count += 1
    if count:
        links = coo_matrix((values, (rows, columns)), shape=(count, int(offsets[-1]))).tocsr()
        eq = vstack([eq, links], format='csr')
        rhs_eq = np.r_[rhs_eq, np.zeros(count)]
    integrality = np.concatenate([p.integrality for p in problems])
    options = {'time_limit': 30.}
    if np.any(integrality):
        options['mip_rel_gap'] = 0.
    solution = linprog(objective, A_eq=eq, b_eq=rhs_eq, A_ub=ub, b_ub=rhs_ub,
                       bounds=[b for p in problems for b in p.bounds],
                       integrality=integrality if np.any(integrality) else None,
                       method='highs', options=options)
    if not solution.success:
        if solution.status == 2:
            failures = {}
            for label, problem in zip(labels, problems):
                try:
                    problem.run()
                except InfeasibleModelError as exc:
                    failures[label] = exc.diagnosis
            if failures:
                raise StochasticInfeasibleError(failures)
        raise RuntimeError('Optimisasi stokastik belum menghasilkan solusi optimal: '+solution.message)

    results, metrics = {}, []
    for s, (label, prob, problem) in enumerate(zip(labels, probabilities, problems)):
        x = solution.x[offsets[s]:offsets[s+1]]
        result = problem.decode(OptimizeResult(success=True, status=0, x=x, fun=float(problem.c @ x)))
        results[label] = result
        metrics.append({'Skenario': label, 'Probabilitas': prob, 'Biaya (USD/tahun)': result.annual_cost,
                        'Energi beban (MWh/tahun)': result.annual_energy, 'Emisi (tCO2/tahun)': result.annual_emissions,
                        'Kontribusi biaya ekspektasian (USD/tahun)': prob*result.annual_cost})

    def average_tables(tables):
        if tables[0] is None:
            return None
        out = tables[0].copy()
        for column in out.select_dtypes(include='number').columns:
            out[column] = sum(prob*table[column].to_numpy() for prob, table in zip(probabilities, tables))
        if 'Jumlah blok' in out:
            out['Jumlah blok'] = tables[0]['Jumlah blok'].to_numpy()
        return out

    def average_table(attribute):
        return average_tables([getattr(r, attribute) for r in results.values()])

    storage_names = next(iter(results.values())).storage_dispatch
    return StochasticResult(summary=average_table('summary'), dispatch=average_table('dispatch'), annual_cost=float(solution.fun),
                            annual_energy=sum(prob*r.annual_energy for prob, r in zip(probabilities, results.values())),
                            annual_emissions=sum(prob*r.annual_emissions for prob, r in zip(probabilities, results.values())),
                            battery_summary=average_table('battery_summary'),
                            storage_dispatch={name: average_tables([r.storage_dispatch[name] for r in results.values()]) for name in storage_names},
                            scenario_results=results, scenario_metrics=pd.DataFrame(metrics), scenario_inputs=scenarios[required].copy(),
                            uncertainty_parameters=selected)
