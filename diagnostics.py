"""Diagnosis terukur dari model yang sama, tanpa mengubah input pengguna."""
import math

import numpy as np
import pandas as pd
from solver_backend import linprog


def diagnose(a_eq, b_eq, a_ub, b_ub, bounds, integrality, context):
    n, t = context['n'], context['t']
    names, scale = context['names'], context['scale']
    demand, available = context['demand'], context['available']
    maximum = context['maximum']
    existing = context.get('existing', np.zeros(n))
    potential = context.get('potential', np.zeros(n))
    storage_specs = context.get('storage_specs', [])
    size = a_eq.shape[1]
    integer = bool(np.any(integrality))
    notes, suggestions = [], []
    report = {'findings': notes, 'suggestions': suggestions}

    def run(objective=None, eq=None, ub=None, rhs=None, limits=None, kinds=None):
        return linprog(np.zeros(size) if objective is None else objective,
                       A_eq=a_eq if eq is None else eq, b_eq=b_eq,
                       A_ub=a_ub if ub is None else ub, b_ub=b_ub if rhs is None else rhs,
                       bounds=bounds if limits is None else limits,
                       integrality=integrality if kinds is None else kinds,
                       method='highs', options={'time_limit': 5., 'mip_rel_gap': 0.} if integer else {'time_limit': 5.})

    effective = existing+np.array([b[1] if b[1] is not None else np.inf for b in bounds[:n]])*scale
    potential_limit = np.where(potential > 0, potential, np.inf)
    if context['integer']:
        potential_limit = existing+np.floor((potential_limit-existing)/scale)*scale
    effective = np.minimum(effective, potential_limit)
    combined = np.minimum(np.where(maximum > 0, maximum, np.inf), np.where(potential > 0, potential, np.inf))
    # Teknologi tanpa batas dan ketersediaan nol tetap memasok nol, bukan NaN.
    contributions = np.zeros_like(available, dtype=float)
    np.multiply(available, effective[:, None], out=contributions, where=available > 0)
    gen_power = contributions.sum(axis=0)
    unused = np.zeros(n)
    np.subtract(combined, effective, out=unused, where=np.isfinite(combined))
    bat_power = sum(spec['config'].existing_power_mw+bounds[spec['nb']][1]*spec['config'].block_mw for spec in storage_specs)
    shortage_bound = np.maximum(0., demand-gen_power-bat_power)
    report['capacity'] = pd.DataFrame({'Teknologi': names, 'Batas input (MW)': maximum,
                                       'Batas efektif (MW)': effective,
                                       'Potensi EBT (MW; 0 = tanpa batas)': potential,
                                       'Batas gabungan (MW)': combined,
                                       'Tanpa batas kapasitas': ~np.isfinite(combined),
                                       'Tidak terpakai karena blok (MW)': unused})
    if np.any(maximum == 0):
        notes.append('Batas kapasitas pembangkit bernilai 0 berarti tanpa batas pembangunan. '
                     'Nilai inf pada batas pasokan menunjukkan tidak ada batas kapasitas; '
                     'profil ketersediaan dan batas emisi tetap berlaku.')
    if np.any(potential > 0):
        notes.append('Potensi EBT membatasi TOTAL kapasitas tahun dasar + eksogen + endogen. '
                     'Batas kapasitas umum dan potensi EBT berlaku bersamaan; nol pada salah satunya tidak menonaktifkan batas positif lainnya.')
    if np.any(shortage_bound > 1e-6):
        h = int(np.argmax(shortage_bound))
        notes.append(f"Batas pasokan pasti kurang pada jam {context['hours'][h]}: beban {demand[h]:.2f} MW, "
                     f"batas pembangkit + daya baterai {gen_power[h]+bat_power:.2f} MW, "
                     f"selisih sedikitnya {shortage_bound[h]:.2f} MW. Batas ini belum memperhitungkan energi baterai.")
    if gen_power.sum()+1e-6 < demand.sum():
        notes.append(f'Energi pembangkitan maksimum hanya {gen_power.sum():.2f} MWh/hari contoh, '
                     f'di bawah kebutuhan {demand.sum():.2f} MWh. Baterai siklik tidak menghasilkan energi baru; '
                     'penambahan baterai saja tidak cukup. Naikkan batas pembangkit yang tersedia atau periksa beban/profil.')
    if np.any(unused > 1e-6):
        notes.append('Ukuran blok membuat sebagian batas kapasitas tidak dapat dibangun. '
                     'Periksa tabel batas efektif; pertimbangkan blok lebih kecil atau batas kapasitas yang mencapai kelipatan berikutnya.')

    # Slack hanya pada keseimbangan daya: cari minimum energi yang tidak terlayani.
    slack_eq = np.pad(a_eq, ((0, 0), (0, t)))
    slack_eq[:t, size:] = np.eye(t)
    relaxed = linprog(np.r_[np.zeros(size), np.ones(t)], A_eq=slack_eq, b_eq=b_eq,
                      A_ub=np.pad(a_ub, ((0, 0), (0, t))), b_ub=b_ub,
                      bounds=list(bounds)+[(0., float(d)) for d in demand],
                      integrality=np.r_[integrality, np.zeros(t)], method='highs',
                      options={'time_limit': 5., 'mip_rel_gap': 0.} if integer else {'time_limit': 5.})
    hourly = pd.DataFrame({'Jam': context['hours'], 'Beban (MW)': demand,
                           'Batas pembangkit (MW)': gen_power,
                           'Batas daya baterai (MW)': bat_power,
                           'Kekurangan pasti dari batas daya (MW)': shortage_bound})
    if relaxed.success:
        unserved = np.maximum(relaxed.x[size:], 0.)
        hourly['Tidak terlayani pada solusi diagnosis (MW)'] = unserved
        report['unserved_mwh_per_day'] = float(unserved.sum())
        notes.append(f'Diagnosis dengan slack beban: minimum energi tidak terlayani {unserved.sum():.2f} MWh/hari contoh '
                     f'({unserved.sum()*context["days"]:.2f} MWh/tahun). '
                     'Jadwal kekurangan pada tabel adalah salah satu solusi minimum; pembagiannya antarjam dapat berbeda.')
    else:
        notes.append('Pencarian minimum kekurangan belum selesai; tabel batas daya tetap dapat digunakan. '
                     'Tidak ada hasil diagnosis numerik yang dinyatakan optimal untuk pemeriksaan ini.')
    report['hourly'] = hourly

    emission_limit = context['emissions_limit']
    if emission_limit is not None:
        objective = np.zeros(size)
        objective[n:n+n*t] = np.repeat(context['emissions'], t)*context['days']
        minimum = run(objective, ub=a_ub[:-1], rhs=b_ub[:-1])
        if minimum.success:
            min_emissions = max(0., float(minimum.fun))
            report['minimum_emissions'] = min_emissions
            if min_emissions > emission_limit+1e-5:
                proposed = math.ceil(min_emissions*100)/100
                notes.append(f'Batas emisi {emission_limit:.2f} tCO2/tahun lebih rendah dari emisi minimum '
                             f'yang dapat dicapai, {min_emissions:.2f} tCO2/tahun, dengan kapasitas/profil/blok/baterai saat ini.')
                rhs = b_ub.copy()
                rhs[-1] = proposed
                if run(rhs=rhs).success:
                    suggestions.append({'Parameter': 'Batas emisi (tCO2/tahun)', 'Saat ini': emission_limit,
                                        'Contoh nilai layak': proposed,
                                        'Keterangan': 'Emisi minimum dibulatkan ke atas; diuji dengan parameter lain tetap.'})
        elif minimum.status == 2:
            notes.append('Menghapus batas emisi saja masih belum menghasilkan solusi layak; '
                         'ada keterbatasan kapasitas, profil, blok, atau baterai yang juga perlu diperbaiki.')
        else:
            notes.append('Pemeriksaan emisi minimum belum selesai; belum ada ambang emisi yang dapat dipastikan.')

    # Uji contoh perubahan satu parameter, tidak mengklaim perubahan minimum.
    for i, name in enumerate(names):
        if maximum[i] == 0:
            continue
        positive = available[i] > 1e-6
        if not positive.any():
            continue
        required = float(np.max(demand[positive]/available[i, positive]))
        proposed = existing[i]+math.ceil(max(0., required-existing[i])/scale[i])*scale[i] if context['integer'] else max(existing[i], required)
        if proposed <= maximum[i]+1e-6:
            continue
        limits = list(bounds)
        limits[i] = (0., (proposed-existing[i])/scale[i])
        if run(limits=limits).success:
            suggestions.append({'Parameter': f'Batas kapasitas (MW) · {name}', 'Saat ini': float(maximum[i]),
                                'Contoh nilai layak': proposed,
                                'Keterangan': 'Satu contoh penambahan kapasitas yang teruji; bukan nilai tambahan minimum.'})

    if context['integer']:
        for i, name in enumerate(names):
            if unused[i] <= 1e-6:
                continue
            for divisor in (2., 4., 10.):
                proposed = scale[i]/divisor
                if proposed < .01:
                    continue
                ub, limits = a_ub.copy(), list(bounds)
                ub[:, i] *= proposed/scale[i]
                limits[i] = (0., float(np.floor((maximum[i]-existing[i])/proposed)) if maximum[i] > 0 else None)
                if run(ub=ub, limits=limits).success:
                    suggestions.append({'Parameter': f'Ukuran blok (MW) · {name}', 'Saat ini': float(scale[i]),
                                        'Contoh nilai layak': proposed,
                                        'Keterangan': 'Ukuran blok lebih kecil yang teruji layak dengan batas kapasitas tetap.'})
                    break

    for i, row_index in context.get('potential_rows', {}).items():
        positive = available[i] > 1e-6
        if not positive.any():
            continue
        required = float(np.max(demand[positive]/available[i, positive]))
        proposed = existing[i]+math.ceil(max(0., required-existing[i])/scale[i])*scale[i] if context['integer'] else max(existing[i], required)
        if proposed <= potential[i]+1e-6:
            continue
        rhs = b_ub.copy()
        rhs[row_index] = proposed-existing[i]
        if run(rhs=rhs).success:
            suggestions.append({'Parameter': f'Potensi EBT (MW) · {names[i]}', 'Saat ini': float(potential[i]),
                'Contoh nilai layak': proposed, 'Keterangan': 'Contoh teruji dengan batas kapasitas lain tetap. Ubah potensi hanya bila didukung data sumber daya; bukan rekomendasi untuk memperbesar potensi fisik.'})

    for spec in storage_specs:
        battery, name, start = spec['config'], spec['name'], spec['ub_start']
        nb, charge, discharge, soc, mode = [spec[k] for k in ('nb', 'charge', 'discharge', 'soc', 'mode')]
        power_limit = battery.existing_power_mw+bounds[nb][1]*battery.block_mw
        notes.append(f'{name} dibatasi {power_limit:g} MW / {power_limit*battery.duration_hours:g} MWh setelah pembulatan blok. '
                     'Periksa daya per blok, batas daya, durasi, efisiensi, dan ketersediaan energi untuk pengisian; '
                     'energi awal dan akhir hari wajib sama.')
        for kind, current in [('power', battery.max_power_mw), ('duration', battery.duration_hours)]:
            for factor in (2., 4., 8.):
                ub, rhs, limits = a_ub.copy(), b_ub.copy(), list(bounds)
                if kind == 'power':
                    proposed = max(current, battery.block_mw)*factor
                    blocks = math.floor((proposed-battery.existing_power_mw)/battery.block_mw)
                    power = battery.existing_power_mw+blocks*battery.block_mw
                    limits[nb] = (0., float(blocks))
                    for h in range(t):
                        ub[start+5*h+3, mode[h]] = -power
                        ub[start+5*h+4, mode[h]] = power
                        rhs[start+5*h+4] = power
                    label = 'Batas daya baterai (MW)' if name == 'Baterai' else f'Batas daya (MW) · {name}'
                else:
                    proposed = current*factor
                    for h in range(t):
                        ub[start+5*h+2, nb] = -battery.block_mw*proposed
                        rhs[start+5*h+2] = battery.existing_power_mw*proposed
                    ub[start+5*t, nb] = -battery.block_mw*proposed
                    rhs[start+5*t] = battery.existing_power_mw*proposed
                    label = 'Durasi baterai (jam)' if name == 'Baterai' else f'Durasi (jam) · {name}'
                if run(ub=ub, rhs=rhs, limits=limits).success:
                    suggestions.append({'Parameter': label, 'Saat ini': current, 'Contoh nilai layak': proposed,
                                        'Keterangan': 'Contoh teruji dengan parameter lain tetap; bukan perubahan minimum.'})
                    break

    if not suggestions:
        notes.append('Belum ditemukan perubahan satu parameter yang teruji layak dalam pemeriksaan terbatas ini. '
                     'Periksa kombinasi batas kapasitas dan emisi, atau tambah daya/durasi baterai jika ada energi pengisian. '
                     'Koreksi beban dan ketersediaan hanya jika data memang keliru.')
    notes.append('Mengubah biaya atau harga karbon tidak memperbaiki kelayakan karena keduanya hanya masuk fungsi tujuan. '
                 'Rekomendasi tidak diterapkan otomatis. Ini diagnosis melalui slack dan uji perubahan parameter, bukan IIS.')
    return report
