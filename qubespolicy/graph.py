# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.

import argparse
import json
import os

import sys

import qubespolicy

parser = argparse.ArgumentParser(description='Graph qrexec policy')
parser.add_argument('--include-ask', action='store_true',
    help='Include `ask` action in graph')
parser.add_argument('--source', action='store', nargs='+',
    help='Limit graph to calls from *source*')
parser.add_argument('--target', action='store', nargs='+',
    help='Limit graph to calls to *target*')
parser.add_argument('--service', action='store', nargs='+',
    help='Limit graph to *service*')
parser.add_argument('--output', action='store',
    help='Write to *output* instead of stdout')
parser.add_argument('--policy-dir', action='store',
    default=qubespolicy.POLICY_DIR,
    help='Look for policy in *policy-dir*')
parser.add_argument('--system-info', action='store',
    help='Load system information from file instead of querying qubesd')
parser.add_argument('--skip-labels', action='store_true',
    help='Do not include service names on the graph, also deduplicate '
         'connections.')

def handle_single_action(args, action):
    '''Get single policy action and output (or not) a line to add'''
    if args.skip_labels:
        service = ''
    else:
        service = action.service
    target = action.target or action.original_target
    # handle forced target=
    if action.rule.override_target:
        target = action.rule.override_target
    if args.target and target not in args.target:
        return ''
    if action.action == qubespolicy.Action.ask:
        if args.include_ask:
            return '  "{}" -> "{}" [label="{}" color=orange];\n'.format(
                action.source, target, service)
    elif action.action == qubespolicy.Action.allow:
        return '  "{}" -> "{}" [label="{}" color=red];\n'.format(
                action.source, target, service)
    return ''

def main(args=None):
    args = parser.parse_args(args)

    output = sys.stdout
    if args.output:
        output = open(args.output, 'w')

    if args.system_info:
        with open(args.system_info) as f_system_info:
            system_info = json.load(f_system_info)
    else:
        system_info = qubespolicy.get_system_info()

    sources = list(system_info['domains'].keys())
    if args.source:
        sources = args.source

    targets = list(system_info['domains'].keys())
    targets.append('$dispvm')
    targets.extend('$dispvm:' + dom for dom in system_info['domains']
        if system_info['domains'][dom]['template_for_dispvms'])

    connections = set()

    output.write('digraph g {\n')
    for service in os.listdir(args.policy_dir):
        if os.path.isdir(os.path.join(args.policy_dir, service)):
            continue
        if args.service and service not in args.service and \
                not any(service.startswith(srv + '+') for srv in args.service):
            continue

        policy = qubespolicy.Policy(service, args.policy_dir)
        for source in sources:
            for target in targets:
                try:
                    action = policy.evaluate(system_info, source, target)
                    line = handle_single_action(args, action)
                    if line in connections:
                        continue
                    if line:
                        output.write(line)
                    connections.add(line)
                except qubespolicy.AccessDenied:
                    continue

    output.write('}\n')
    if args.output:
        output.close()

if __name__ == '__main__':
    sys.exit(main())
