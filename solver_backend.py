"""Antarmuka matriks LP/MILP: HiGHS atau Gurobi, terisolasi per eksekusi."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic

import numpy as np
from scipy.optimize import OptimizeResult, linprog as scipy_linprog
from scipy.sparse import csr_matrix


@dataclass(frozen=True)
class SolverSettings:
    name: str = 'HiGHS'
    license_mode: str = 'local'
    access_id: str = field(default='', repr=False)
    secret: str = field(default='', repr=False)
    license_id: int = field(default=0, repr=False)

    def validate(self):
        if self.name not in ('HiGHS', 'Gurobi'):
            raise ValueError('Pilihan solver harus HiGHS atau Gurobi.')
        if self.license_mode not in ('local', 'wls'):
            raise ValueError('Mode lisensi Gurobi harus local atau wls.')
        if self.name == 'Gurobi' and self.license_mode == 'wls':
            if not self.access_id.strip() or not self.secret.strip():
                raise ValueError('Kredensial cloud WLS belum lengkap: isi WLSACCESSID, WLSSECRET, dan LICENSEID.')
            if isinstance(self.license_id, bool) or not isinstance(self.license_id, (int, np.integer)) or self.license_id <= 0:
                raise ValueError('LICENSEID WLS harus berupa bilangan bulat positif.')


class _Session:
    def __init__(self, settings):
        self.settings = settings
        self.env = None
        self.gp = None

    def environment(self):
        if self.env is not None:
            return self.gp, self.env
        try:
            import gurobipy as gp
        except ImportError:
            raise RuntimeError('Gurobi belum tersedia pada server ini. Pasang gurobipy sesuai requirements, atau pilih HiGHS.') from None
        env = None
        try:
            env = gp.Env(empty=True)
            # Matikan log sebelum kredensial diterapkan; setiap sesi mempunyai
            # environment sendiri, tanpa mengubah os.environ/default environment.
            env.setParam('OutputFlag', 0)
            if self.settings.license_mode == 'wls':
                env.setParam('WLSACCESSID', self.settings.access_id.strip())
                env.setParam('WLSSECRET', self.settings.secret.strip())
                env.setParam('LICENSEID', int(self.settings.license_id))
            env.start()
        except gp.GurobiError as exc:
            if env is not None:
                try:
                    env.dispose()
                except gp.GurobiError:
                    pass
            raise _gurobi_error(exc) from None
        self.gp, self.env = gp, env
        return gp, env

    def close(self):
        if self.env is not None:
            try:
                self.env.dispose()
            except self.gp.GurobiError as exc:
                raise _gurobi_error(exc) from None
            finally:
                self.env = None


_session = ContextVar('genora_solver_session', default=None)


@contextmanager
def solver_session(settings=None):
    settings = settings or SolverSettings()
    settings.validate()
    session = _Session(settings)
    token = _session.set(session)
    try:
        yield
    finally:
        try:
            session.close()
        finally:
            _session.reset(token)


def _gurobi_error(exc):
    code = getattr(exc, 'errno', '?')
    if code == 10010:
        detail = 'Ukuran model melebihi batas lisensi Gurobi yang terdeteksi. Konfigurasikan lisensi penuh atau pilih HiGHS.'
    elif code == 10009:
        detail = 'Lisensi Gurobi tidak dapat digunakan. Periksa lisensi pada komputer/server atau konfigurasi WLS.'
    else:
        detail = 'Periksa instalasi, lisensi, atau koneksi WLS pada komputer/server yang menjalankan GENORA.'
    # Pesan asli vendor dapat memuat informasi konfigurasi; jangan tampilkan
    # atau simpan pesan tersebut di hasil, traceback aplikasi, atau ekspor.
    return RuntimeError(f'Gurobi gagal (kode {code}). {detail}')


def linprog(c, A_ub=None, b_ub=None, A_eq=None, b_eq=None, bounds=(0, None),
            method='highs', integrality=None, options=None, **kwargs):
    session = _session.get()
    if session is None or session.settings.name == 'HiGHS':
        return scipy_linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
            bounds=bounds, method=method, integrality=integrality, options=options, **kwargs)
    if kwargs:
        raise ValueError('Argumen solver tambahan tidak didukung untuk Gurobi.')
    gp, env = session.environment()
    model = None
    try:
        model = gp.Model(env=env)
        model.setParam('OutputFlag', 0)
        model.setParam('Threads', 2)
        options = options or {}
        if options.get('time_limit') is not None:
            model.setParam('TimeLimit', float(options['time_limit']))
        if options.get('mip_rel_gap') is not None:
            model.setParam('MIPGap', float(options['mip_rel_gap']))
        c = np.asarray(c, dtype=float)
        kinds = np.zeros(len(c), dtype=int) if integrality is None else np.broadcast_to(integrality, c.shape)
        if not np.isin(kinds, [0, 1]).all():
            raise ValueError('Gurobi GENORA mendukung variabel kontinu dan integer (termasuk biner).')
        if bounds is None:
            limits = [(0., None)]*len(c)
        elif len(bounds) == 2 and not isinstance(bounds[0], (list, tuple, np.ndarray)):
            limits = [bounds]*len(c)
        else:
            limits = bounds
        lower = np.array([-gp.GRB.INFINITY if lo is None else lo for lo, _ in limits], dtype=float)
        upper = np.array([gp.GRB.INFINITY if hi is None else hi for _, hi in limits], dtype=float)
        types = np.where(kinds == 1, gp.GRB.INTEGER, gp.GRB.CONTINUOUS)
        x = model.addMVar(len(c), lb=lower, ub=upper, obj=c, vtype=types)
        model.ModelSense = gp.GRB.MINIMIZE
        for matrix, rhs, sense in [(A_eq, b_eq, gp.GRB.EQUAL), (A_ub, b_ub, gp.GRB.LESS_EQUAL)]:
            if matrix is not None:
                matrix = csr_matrix(matrix)
                if matrix.shape[0]:
                    model.addMConstr(matrix, x, sense, np.asarray(rhs, dtype=float))
        started = monotonic()
        model.optimize()
        if model.Status == gp.GRB.INF_OR_UNBD:
            model.setParam('DualReductions', 0)
            model.reset()
            if options.get('time_limit') is not None:
                model.setParam('TimeLimit', max(.001, float(options['time_limit'])-(monotonic()-started)))
            model.optimize()
        raw_status = model.Status
        status = {gp.GRB.OPTIMAL: 0, gp.GRB.INFEASIBLE: 2, gp.GRB.UNBOUNDED: 3,
                  gp.GRB.TIME_LIMIT: 1, gp.GRB.ITERATION_LIMIT: 1, gp.GRB.NODE_LIMIT: 1,
                  gp.GRB.INTERRUPTED: 1}.get(raw_status, 4)
        has_solution = model.SolCount > 0
        return OptimizeResult(success=status == 0 and has_solution, status=status,
            message=f'Gurobi status {raw_status}', x=x.X.copy() if has_solution else None,
            fun=float(model.ObjVal) if has_solution else None)
    except gp.GurobiError as exc:
        raise _gurobi_error(exc) from None
    finally:
        if model is not None:
            try:
                model.dispose()
            except gp.GurobiError as exc:
                raise _gurobi_error(exc) from None
