#!/usr/bin/env python3
"""Run offline component suites; no real printer or camera is contacted."""
import argparse
import os
from pathlib import Path
import subprocess
from components import add_selection_arguments, environment_python, selected_components

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    add_selection_arguments(parser)
    parser.add_argument('--python',type=Path,help='Existing compatible interpreter for selected components; no packages are installed.')
    args=parser.parse_args()
    names=selected_components(args)
    if args.list:
        print('\n'.join(names))
        return
    environment=dict(os.environ,PRINTER_MODE='mock',PRINTER_ALLOW_MOTION='0')
    environment.pop('SSH_HOST',None)
    for name in names:
        directory=ROOT/name
        python=args.python.expanduser().resolve() if args.python else environment_python(directory)
        if not python.is_file():
            raise SystemExit(f'No interpreter for {name}. Run scripts/setup.py --component {name}, or pass --python.')
        if name=='dashboard':
            (ROOT/'sample-vision/results/images').mkdir(parents=True,exist_ok=True)
        print(f'Checking {name} with {python}',flush=True)
        subprocess.run([str(python),'-m','pip','check'],cwd=directory,env=environment,check=True)
        tests=['-s','.','-p','test_viewport.py'] if name=='camera-adapter' else ['-s','tests']
        subprocess.run([str(python),'-m','unittest','discover',*tests,'-v'],cwd=directory,env=environment,check=True)


if __name__=='__main__':
    main()
