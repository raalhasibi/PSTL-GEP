"""Konversi formulir penyimpanan ke konfigurasi model."""
import pandas as pd

from model import BatteryConfig, validate_names


STORAGE_COLUMNS = {
    'Daya blok (MW)': 'block_mw', 'Durasi (jam)': 'duration_hours',
    'Batas daya (MW)': 'max_power_mw', 'O&M daya (USD/kW/tahun)': 'power_cost',
    'O&M energi (USD/kWh/tahun)': 'energy_cost', 'Efisiensi round-trip (0–1)': 'round_trip_efficiency',
    'Biaya operasi (USD/MWh keluar)': 'discharge_cost', 'Investasi daya (USD/kW)': 'investment_power',
    'Investasi energi (USD/kWh)': 'investment_energy', 'Umur aset (tahun)': 'lifetime',
}


def empty_storage_table():
    return pd.DataFrame({'Teknologi': pd.Series(dtype=str), **{col: pd.Series(dtype=float) for col in STORAGE_COLUMNS}})


def add_storage(table, name, config, generator_names):
    name = name.strip()
    validate_names(list(generator_names)+table.Teknologi.tolist()+[name])
    config.validate()
    return pd.concat([table, pd.DataFrame([{'Teknologi': name, **{column: getattr(config, field) for column, field in STORAGE_COLUMNS.items()}}])], ignore_index=True)


def storage_configs(table, validate=True):
    validate_names(table.Teknologi.tolist())
    configs = {}
    for _, row in table.iterrows():
        config = BatteryConfig(**{field: float(row[column]) for column, field in STORAGE_COLUMNS.items()})
        if validate:
            config.validate()
        configs[row.Teknologi] = config
    return configs
