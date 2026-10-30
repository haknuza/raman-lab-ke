#!/usr/bin/env python3
"""Install isolated component environments; never connect to hardware."""
import argparse
from pathlib import Path
import subprocess
import sys
import venv
from components import add_selection_arguments, environment_python, selected_components

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    add_selection_arguments(parser)
    args=parser.parse_args()
    components=selected_components(args)
    if args.list:
        print('\n'.join(components))
        return
    if sys.version_info < (3,11):
        parser.error('Use Python 3.11 or newer.')
    for component in components:
        directory=ROOT/component
        environment=directory/'.venv'
        if not environment.exists():venv.EnvBuilder(with_pip=True).create(environment)
        python=environment_python(directory)
        subprocess.run([str(python),'-m','pip','install','-r',str(directory/'requirements.txt')],check=True)
        subprocess.run([str(python),'-m','pip','check'],check=True)
    if 'sample-vision' in components:
        (ROOT/'sample-vision/results/images').mkdir(parents=True,exist_ok=True)
    if 'dashboard' in components:
        (ROOT/'dashboard/results').mkdir(parents=True,exist_ok=True)
    print('Setup complete. No hardware connection or movement was requested.')

if __name__=='__main__':main()
