"""Component selection shared by setup and offline checks."""
import os
from pathlib import Path

CORE = ('sample-vision', 'printer-control')
ALL = CORE + ('dashboard', 'camera-adapter')


def add_selection_arguments(parser):
    parser.add_argument('--component', action='append', choices=ALL,
                        help='Select a component; repeat to select several. Default: camera scanner and printer.')
    parser.add_argument('--with-dashboard', action='store_true', help='Include the retained chat/erasing dashboard.')
    parser.add_argument('--with-iphone', action='store_true', help='Include the optional Blackmagic phone adapter.')
    parser.add_argument('--list', action='store_true', help='List selected components without installing or running anything.')


def selected_components(args):
    result = list(args.component or CORE)
    if args.with_dashboard:
        result.append('dashboard')
    if args.with_iphone:
        result.append('camera-adapter')
    return list(dict.fromkeys(result))


def environment_python(directory):
    environment = Path(directory)/'.venv'
    return environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
