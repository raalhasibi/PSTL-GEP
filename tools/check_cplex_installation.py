"""Periksa runtime CPLEX lokal menggunakan model sintetis tanpa data pengguna."""
import json
import re
import subprocess
import tempfile
from pathlib import Path


executables = [
    Path(r'C:\Program Files\IBM\ILOG\CPLEX_Studio2211\cplex\bin\x64_win64\cplex.exe'),
    Path(r'C:\Program Files\IBM\ILOG\CPLEX_Studio221\cplex\bin\x64_win64\cplex.exe'),
]
with tempfile.TemporaryDirectory(prefix='genora_cplex_check_') as tmp:
    directory = Path(tmp).resolve()
    assert directory.parent == Path(tempfile.gettempdir()).resolve()
    count = 2001
    lines = ['Minimize', ' obj: '+' + '.join(f'x{i}' for i in range(count)), 'Subject To']
    lines += [f' c{i}: x{i} >= 1' for i in range(count)]
    lines += ['Bounds']+[f' 0 <= x{i} <= 2' for i in range(count)]+['End']
    problem = directory/'license_probe.lp'
    problem.write_text('\n'.join(lines), encoding='ascii')
    for executable in executables:
        if not executable.is_file():
            continue
        try:
            run = subprocess.run([str(executable), '-c', 'set threads 1', 'set timelimit 10',
                                  f'read {problem.name}', 'optimize', 'display solution objective', 'quit'],
                                 cwd=directory, capture_output=True, text=True, timeout=30,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            output = run.stdout+'\n'+run.stderr
            version = re.search(r'Version identifier:\s*([^\r\n]+)', output)
            objectives = re.findall(r'Objective\s*(?:=|:)\s*([-+0-9.eE]+)', output, re.I)
            objective = float(objectives[-1]) if objectives else None
            print(json.dumps({'installation': str(executable.parent.parent.parent),
                'version': version.group(1) if version else None,
                'variables': count, 'constraints': count, 'exit_code': run.returncode,
                'optimal': bool(re.search(r'(optimal|solved)', output, re.I)) and objective is not None,
                'objective': objective, 'expected_objective': count,
                'error_codes': re.findall(r'CPLEX Error\s+(\d+)', output),
                'community_limit_detected': 'problem size limits exceeded' in output.lower() or '1016' in output,
            }))
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({'installation': str(executable), 'check_error': type(exc).__name__}))
