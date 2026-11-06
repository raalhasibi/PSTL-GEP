import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.optimize import linprog as scipy_linprog
from streamlit.testing.v1 import AppTest

from model import BatteryConfig, InfeasibleModelError, example_inputs, solve
from multiyear import solve_multiyear, build_multiyear_problem
from stochastic import solve_stochastic
from solver_backend import SolverSettings, linprog, solver_session
from solver_ui import settings_for_run, WLS_LICENSE, SESSION_CREDENTIALS, SERVER_CREDENTIALS
from scenario_manager import initialize, save_active


class GurobiError(Exception):
    def __init__(self, errno):
        self.errno = errno


def fake_gurobi(fail_start=False, force_status=None):
    """Simulasi kontrak API Gurobi dengan SciPy, tanpa menghubungi server lisensi."""
    grb = SimpleNamespace(INFINITY=1e100, INTEGER='I', CONTINUOUS='C', MINIMIZE=1, EQUAL='=', LESS_EQUAL='<',
        OPTIMAL=2, INFEASIBLE=3, INF_OR_UNBD=4, UNBOUNDED=5, TIME_LIMIT=9, ITERATION_LIMIT=7, NODE_LIMIT=8, INTERRUPTED=11)
    envs, models = [], []

    class Env:
        def __init__(self, empty=False):
            self.params = {}
            self.closed = False
            envs.append(self)

        def setParam(self, key, value):
            self.params[key] = value

        def start(self):
            if fail_start:
                raise GurobiError(10009)

        def dispose(self):
            self.closed = True

    class Model:
        def __init__(self, env):
            self.env, self.params, self.constraints = env, {}, []
            self.closed = False
            models.append(self)

        def setParam(self, key, value):
            self.params[key] = value

        def addMVar(self, n, lb, ub, obj, vtype):
            self.lb, self.ub, self.c, self.types = lb, ub, obj, vtype
            self.x = SimpleNamespace(X=None)
            return self.x

        def addMConstr(self, matrix, x, sense, rhs):
            self.constraints.append((matrix, sense, rhs))

        def optimize(self):
            eq = next(((a, b) for a, sense, b in self.constraints if sense == '='), (None, None))
            ub = next(((a, b) for a, sense, b in self.constraints if sense == '<'), (None, None))
            integrality = (self.types == 'I').astype(int)
            bounds = [(None if lo <= -grb.INFINITY else lo, None if hi >= grb.INFINITY else hi) for lo, hi in zip(self.lb, self.ub)]
            r = scipy_linprog(self.c, A_eq=eq[0], b_eq=eq[1], A_ub=ub[0], b_ub=ub[1], bounds=bounds,
                integrality=integrality if integrality.any() else None, method='highs')
            self.Status = force_status if force_status is not None else {0:2, 1:9, 2:3, 3:5}.get(r.status, 12)
            self.SolCount = int(r.success)
            self.x.X, self.ObjVal = r.x, r.fun

        def reset(self):
            pass

        def dispose(self):
            self.closed = True

    return SimpleNamespace(Env=Env, Model=Model, GRB=grb, GurobiError=GurobiError, envs=envs, models=models)


class SolverBackendTests(unittest.TestCase):
    def test_lp_integer_sparse_multiyear_stochastic_match_highs(self):
        tech, profile = example_inputs()
        tech = tech.iloc[[1]].copy()
        baseline = solve(tech, profile, capacity_model='integer')
        fake = fake_gurobi()
        with patch.dict(sys.modules, {'gurobipy': fake}), solver_session(SolverSettings(name='Gurobi')):
            integer = solve(tech, profile, capacity_model='integer')
            self.assertAlmostEqual(integer.annual_cost, baseline.annual_cost)
            years = solve_multiyear(tech, profile, planning_years=2, annual_growth=.1)
            self.assertAlmostEqual(years.year_results[2027].dispatch['Beban (MW)'].max(), 121.)
            import pandas as pd
            scenarios = pd.DataFrame({'Skenario': ['A', 'B'], 'Probabilitas': [.4, .6], 'Faktor beban': [1., 1.1]})
            stochastic = solve_stochastic(tech, profile, scenarios, problem_builder=build_multiyear_problem, planning_years=2)
            self.assertEqual(len(stochastic.year_results), 2)
            self.assertGreater(stochastic.npv_cost, 0.)
        self.assertEqual(len(fake.envs), 1)
        self.assertTrue(fake.envs[0].closed)
        self.assertTrue(all(m.closed for m in fake.models))

    def test_infeasibility_diagnosis_uses_selected_backend(self):
        tech, profile = example_inputs()
        tech = tech.iloc[[1]].copy()
        tech['Batas kapasitas (MW)'] = 80.
        fake = fake_gurobi()
        with patch.dict(sys.modules, {'gurobipy': fake}), solver_session(SolverSettings(name='Gurobi')):
            with self.assertRaises(InfeasibleModelError) as exc:
                solve(tech, profile)
            self.assertGreater(exc.exception.diagnosis['unserved_mwh_per_day'], 0.)
        self.assertGreater(len(fake.models), 1)
        self.assertEqual(len(fake.envs), 1)
        self.assertTrue(all(m.closed for m in fake.models))

    def test_time_limit_result_is_not_accepted_as_optimal(self):
        fake = fake_gurobi(force_status=9)
        with patch.dict(sys.modules, {'gurobipy': fake}), solver_session(SolverSettings(name='Gurobi')):
            r = linprog([1.], bounds=[(0., 1.)])
        self.assertFalse(r.success)
        self.assertEqual(r.status, 1)

    def test_cloud_parameters_are_isolated_and_not_exported_to_scenarios(self):
        fake = fake_gurobi()
        before = dict(os.environ)
        for access, secret, license_id in [('test-access-a', 'test-secret-a', 1), ('test-access-b', 'test-secret-b', 2)]:
            config = SolverSettings('Gurobi', 'wls', access, secret, license_id)
            self.assertNotIn(secret, repr(config))
            with patch.dict(sys.modules, {'gurobipy': fake}), solver_session(config):
                self.assertTrue(linprog([1.], bounds=[(0.,1.)]).success)
        self.assertEqual(fake.envs[0].params['WLSACCESSID'], 'test-access-a')
        self.assertEqual(fake.envs[1].params['LICENSEID'], 2)
        self.assertTrue(all(e.closed for e in fake.envs))
        self.assertEqual(dict(os.environ), before)
        state = {}
        initialize(state)
        state.update(solver_choice='Gurobi', gurobi_license_mode=WLS_LICENSE,
                     gurobi_wls_access_id='test-access-a', gurobi_wls_secret='test-secret-a', gurobi_wls_license_id=1)
        save_active(state)
        self.assertNotIn('test-secret-a', repr(state['experiment_cases']))

    def test_license_failure_never_falls_back_or_leaks_credentials(self):
        fake = fake_gurobi(fail_start=True)
        with patch.dict(sys.modules, {'gurobipy': fake}), patch('solver_backend.scipy_linprog') as highs:
            with self.assertRaises(RuntimeError) as exc, solver_session(SolverSettings('Gurobi', 'wls', 'test-access', 'test-secret', 1)):
                linprog([1.])
            highs.assert_not_called()
        self.assertNotIn('test-secret', str(exc.exception))
        self.assertTrue(fake.envs[0].closed)
        self.assertTrue(linprog([1.], bounds=[(0.,1.)]).success)

    def test_missing_cloud_fields_and_server_credentials(self):
        state = {'solver_choice': 'Gurobi', 'gurobi_license_mode': WLS_LICENSE, 'gurobi_credential_source': SESSION_CREDENTIALS}
        with self.assertRaises(ValueError):
            settings_for_run(state)
        state['gurobi_credential_source'] = SERVER_CREDENTIALS
        result = settings_for_run(state, secrets={'gurobi': {'WLSACCESSID': 'a', 'WLSSECRET': 'b', 'LICENSEID': 2}}, environ={})
        self.assertEqual(result.license_mode, 'wls')
        self.assertEqual(result.license_id, 2)
        env = {'GUROBI_WLSACCESSID':'x', 'GUROBI_WLSSECRET':'y', 'GUROBI_LICENSEID':'3'}
        self.assertEqual(settings_for_run(state, secrets={}, environ=env).license_id, 3)


class SolverAppTests(unittest.TestCase):
    def test_solver_switch_cloud_missing_fields_and_redacted_signature(self):
        app = AppTest.from_file('app.py').run(timeout=30)
        next(w for w in app.button if w.label == 'Jalankan Optimisasi').click().run(timeout=30)
        self.assertEqual(len(app.metric), 3)
        app.selectbox(key='solver_choice').set_value('Gurobi').run(timeout=30)
        self.assertEqual(len(app.metric), 0)
        app.selectbox(key='gurobi_license_mode').set_value(WLS_LICENSE).run(timeout=30)
        app.selectbox(key='gurobi_credential_source').set_value(SESSION_CREDENTIALS).run(timeout=30)
        next(w for w in app.button if w.label == 'Jalankan Optimisasi').click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('WLS' in e.value for e in app.error))
        app.text_input(key='gurobi_wls_access_id').set_value('test-access')
        app.text_input(key='gurobi_wls_secret').set_value('test-secret').run(timeout=30)
        self.assertNotIn('test-secret', app.session_state['input_signature'])
        self.assertNotIn('test-secret', repr(app.session_state['experiment_cases']))
        fake = fake_gurobi()
        with patch.dict(sys.modules, {'gurobipy': fake}):
            next(w for w in app.button if w.label == 'Jalankan Optimisasi').click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 3)
        self.assertTrue(any('Solver: Gurobi' in c.value for c in app.caption))


if __name__ == '__main__':
    unittest.main()
