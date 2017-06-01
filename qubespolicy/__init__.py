# coding=utf-8
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2013-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2013-2017  Marek Marczykowski-Górecki
#                                   <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

''' Qrexec policy parser and evaluator '''
import enum
import itertools
import json
import os
import os.path
import socket
import subprocess

# don't import 'qubes.config' please, it takes 0.3s
QREXEC_CLIENT = '/usr/lib/qubes/qrexec-client'
QUBES_RPC_MULTIPLEXER_PATH = '/usr/lib/qubes/qubes-rpc-multiplexer'
POLICY_DIR = '/etc/qubes-rpc/policy'
QUBESD_INTERNAL_SOCK = '/var/run/qubesd.internal.sock'


class AccessDenied(Exception):
    ''' Raised when qrexec policy denied access '''
    pass


class PolicySyntaxError(AccessDenied):
    ''' Syntax error in qrexec policy, abort parsing '''
    def __init__(self, filename, lineno, msg):
        super(PolicySyntaxError, self).__init__(
            '{}:{}: {}'.format(filename, lineno, msg))


class Action(enum.Enum):
    ''' Action as defined by policy '''
    allow = 1
    deny = 2
    ask = 3


def verify_target_value(system_info, value):
    ''' Check if given value names valid target

    This function check if given value is not only syntactically correct,
    but also if names valid service call target (existing domain,
    or valid $dispvm like keyword)

    :param system_info: information about the system
    :param value: value to be checked
    '''
    if value == '$dispvm':
        return True
    elif value.startswith('$dispvm:'):
        dispvm_base = value.split(':', 1)[1]
        if dispvm_base not in system_info['domains']:
            return False
        dispvm_base_info = system_info['domains'][dispvm_base]
        return bool(dispvm_base_info['dispvm_allowed'])
    else:
        return value in system_info['domains']


def verify_special_value(value, for_target=True):
    '''
    Verify if given special VM-specifier ('$...') is valid

    :param value: value to verify
    :param for_target: should classify target-only values as valid (
    '$default', '$dispvm')
    :return: True or False
    '''
    # pylint: disable=too-many-return-statements

    if value.startswith('$tag:') and len(value) > len('$tag:'):
        return True
    elif value.startswith('$type:') and len(value) > len('$type:'):
        return True
    elif value == '$anyvm':
        return True
    elif value.startswith('$dispvm:') and for_target:
        return True
    elif value == '$dispvm' and for_target:
        return True
    elif value == '$default' and for_target:
        return True
    return False


class PolicyRule(object):
    ''' A single line of policy file '''
    def __init__(self, line, filename=None, lineno=None):
        '''
        Load a single line of qrexec policy and check its syntax.
        Do not verify existence of named objects.

        :raise PolicySyntaxError: when syntax error is found

        :param line: a single line of actual qrexec policy (not a comment,
        empty line or $include)
        :param filename: name of the file from which this line is loaded
        :param lineno: line number from which this line is loaded
        '''

        self.lineno = lineno
        self.filename = filename

        try:
            self.source, self.target, self.full_action = line.split()
        except ValueError:
            raise PolicySyntaxError(filename, lineno, 'wrong number of fields')

        (action, *params) = self.full_action.split(',')
        try:
            self.action = Action[action]
        except KeyError:
            raise PolicySyntaxError(filename, lineno,
                'invalid action: {}'.format(action))

        #: alternative target, used instead of the one specified by the caller
        self.override_target = None

        #: alternative user, used instead of vm.default_user
        self.override_user = None

        #: default target when asking the user for confirmation
        self.default_target = None

        for param in params:
            try:
                param_name, value = param.split('=')
            except ValueError:
                raise PolicySyntaxError(filename, lineno,
                    'invalid action parameter syntax: {}'.format(param))
            if param_name == 'target':
                if self.action == Action.deny:
                    raise PolicySyntaxError(filename, lineno,
                        'target= option not allowed for deny action')
                self.override_target = value
            elif param_name == 'user':
                if self.action == Action.deny:
                    raise PolicySyntaxError(filename, lineno,
                        'user= option not allowed for deny action')
                self.override_user = value
            elif param_name == 'default_target':
                if self.action != Action.ask:
                    raise PolicySyntaxError(filename, lineno,
                        'default_target= option allowed only for ask action')
                self.default_target = value
            else:
                raise PolicySyntaxError(filename, lineno,
                    'invalid option {} for {} action'.format(param, action))

        # verify special values
        if self.source.startswith('$'):
            if not verify_special_value(self.source, False):
                raise PolicySyntaxError(filename, lineno,
                    'invalid source specification: {}'.format(self.source))

        if self.target.startswith('$'):
            if not verify_special_value(self.target, True):
                raise PolicySyntaxError(filename, lineno,
                    'invalid target specification: {}'.format(self.target))

        if self.target == '$default' \
                and self.action == Action.allow \
                and self.override_target is None:
            raise PolicySyntaxError(filename, lineno,
                'allow action for $default rule must specify target= option')

        if self.override_target is not None:
            if self.override_target.startswith('$') and not \
                    self.override_target.startswith('$dispvm'):
                raise PolicySyntaxError(filename, lineno,
                    'target= option needs to name specific target')

    @staticmethod
    def is_match_single(system_info, policy_value, value):
        '''
        Evaluate if a single value (VM name or '$default') matches policy
        specification

        :param system_info: information about the system
        :param policy_value: value from qrexec policy (either self.source or
        self.target)
        :param value: value to be compared (source or target)
        :return: True or False
        '''
        # pylint: disable=too-many-return-statements

        # not specified target matches only with $default and $anyvm policy
        # entry
        if value == '$default' or value == '':
            return policy_value in ('$default', '$anyvm')

        # if specific target used, check if it's valid
        # this function (is_match_single) is also used for checking call source
        # values, but this isn't a problem, because it will always be a
        # domain name (not $dispvm or such) - this is guaranteed by a nature
        # of qrexec call
        if not verify_target_value(system_info, value):
            return False

        # allow any _valid_, non-dom0 target
        if policy_value == '$anyvm':
            return value != 'dom0'

        # exact match, including $dispvm*
        if value == policy_value:
            return True

        # if $dispvm* not matched above, reject it; missing ':' is
        # intentional - handle both '$dispvm' and '$dispvm:xxx'
        if value.startswith('$dispvm'):
            return False

        # at this point, value name a specific target
        domain_info = system_info['domains'][value]

        if policy_value.startswith('$tag:'):
            tag = policy_value.split(':', 1)[1]
            return tag in domain_info['tags']

        if policy_value.startswith('$type:'):
            type_ = policy_value.split(':', 1)[1]
            return type_ == domain_info['type']

        return False

    def is_match(self, system_info, source, target):
        '''
        Check if given (source, target) matches this policy line.

        :param system_info: information about the system - available VMs,
        their types, labels, tags etc. as returned by
        :py:func:`app_to_system_info`
        :param source: name of the source VM
        :param target: name of the target VM, or None if not specified
        :return: True or False
        '''

        if not self.is_match_single(system_info, self.source, source):
            return False
        if not self.is_match_single(system_info, self.target, target):
            return False
        return True

    def expand_target(self, system_info):
        '''
        Return domains matching target of this policy line

        :param system_info: information about the system
        :return: matching domains
        '''

        if self.target.startswith('$tag:'):
            tag = self.target.split(':', 1)[1]
            for name, domain in system_info['domains'].items():
                if tag in domain['tags']:
                    yield name
        elif self.target.startswith('$type:'):
            type_ = self.target.split(':', 1)[1]
            for name, domain in system_info['domains'].items():
                if type_ == domain['type']:
                    yield name
        elif self.target == '$anyvm':
            for name, domain in system_info['domains'].items():
                if name != 'dom0':
                    yield name
                if domain['dispvm_allowed']:
                    yield '$dispvm:' + name
            yield '$dispvm'
        elif self.target.startswith('$dispvm:'):
            dispvm_base = self.target.split(':', 1)[1]
            try:
                if system_info['domains'][dispvm_base]['dispvm_allowed']:
                    yield self.target
            except KeyError:
                # TODO log a warning?
                pass
        elif self.target == '$dispvm':
            yield self.target
        else:
            if self.target in system_info['domains']:
                yield self.target

    def expand_override_target(self, system_info, source):
        '''
        Replace '$dispvm' with specific '$dispvm:...' value, based on qrexec
        call source.

        :param system_info: System information
        :param source: Source domain name
        :return: :py:attr:`override_target` with '$dispvm' substituted
        '''
        if self.override_target == '$dispvm':
            if system_info['domains'][source]['default_dispvm'] is None:
                return None
            return '$dispvm:' + system_info['domains'][source]['default_dispvm']
        else:
            return self.override_target


class PolicyAction(object):
    ''' Object representing positive policy evaluation result -
    either ask or allow action '''
    def __init__(self, service, source, target, rule, original_target,
            targets_for_ask=None):
        #: service name
        self.service = service
        #: calling domain
        self.source = source
        #: target domain the service should be connected to, None if
        # not chosen yet
        if targets_for_ask is None or target in targets_for_ask:
            self.target = target
        else:
            # TODO: log a warning?
            self.target = None
        #: original target specified by the caller
        self.original_target = original_target
        #: targets for the user to choose from
        self.targets_for_ask = targets_for_ask
        #: policy rule from which this action is derived
        self.rule = rule
        if rule.action == Action.deny:
            # this should be really rejected by Policy.eval()
            raise AccessDenied(
                'denied by policy {}:{}'.format(rule.filename, rule.lineno))
        elif rule.action == Action.ask:
            assert targets_for_ask is not None
        elif rule.action == Action.allow:
            assert targets_for_ask is None
            assert target is not None
        self.action = rule.action

    def handle_user_response(self, response, target=None):
        '''
        Handle user response for the 'ask' action

        :param response: whether the call was allowed or denied (bool)
        :param target: target chosen by the user (if reponse==True)
        :return: None
        '''
        assert self.action == Action.ask
        assert self.target is None
        if response:
            assert target in self.targets_for_ask
            self.target = target
            self.action = Action.allow
        else:
            self.action = Action.deny
            raise AccessDenied(
                'denied by the user {}:{}'.format(self.rule.filename,
                    self.rule.lineno))

    def execute(self, caller_ident):
        ''' Execute allowed service call

        :param caller_ident: Service caller ident (`process_ident,source_name,
        source_id`)
        '''
        assert self.action == Action.allow
        assert self.target is not None

        if self.target == 'dom0':
            cmd = '{multiplexer} {service} {source} {original_target}'.format(
                multiplexer=QUBES_RPC_MULTIPLEXER_PATH,
                service=self.service,
                source=self.source,
                original_target=self.original_target)
        else:
            cmd = '{user}:QUBESRPC {service} {source}'.format(
                user=(self.rule.override_user or 'DEFAULT'),
                service=self.service,
                source=self.source)
        if self.target.startswith('$dispvm:'):
            target = self.spawn_dispvm()
            dispvm = True
        else:
            target = self.target
            dispvm = False
            self.ensure_target_running()
        qrexec_opts = ['-d', target, '-c', caller_ident]
        if dispvm:
            qrexec_opts.append('-W')
        try:
            subprocess.call([QREXEC_CLIENT] + qrexec_opts + [cmd])
        finally:
            if dispvm:
                self.cleanup_dispvm(target)


    def spawn_dispvm(self):
        '''
        Create and start Disposable VM based on AppVM specified in
        :py:attr:`target`
        :return: name of new Disposable VM
        '''
        base_appvm = self.target.split(':', 1)[1]
        dispvm_name = qubesd_call(base_appvm, 'internal.vm.Create.DispVM')
        dispvm_name = dispvm_name.decode('ascii')
        qubesd_call(dispvm_name, 'internal.vm.Start')
        return dispvm_name

    def ensure_target_running(self):
        '''
        Start domain if not running already

        :return: None
        '''
        try:
            qubesd_call(self.target, 'internal.vm.Start')
        except QubesMgmtException as e:
            if e.exc_type == 'QubesVMNotHaltedError':
                pass
            else:
                raise

    @staticmethod
    def cleanup_dispvm(dispvm):
        '''
        Kill and remove Disposable VM

        :param dispvm: name of Disposable VM
        :return: None
        '''
        qubesd_call(dispvm, 'internal.vm.CleanupDispVM')


class Policy(object):
    ''' Full policy for a given service

    Usage:
    >>> system_info = get_system_info()
    >>> policy = Policy('some-service')
    >>> action = policy.evaluate(system_info, 'source-name', 'target-name')
    >>> if action.action == Action.ask:
            (... ask the user, see action.targets_for_ask ...)
    >>>     action.handle_user_response(response, target_chosen_by_user)
    >>> action.execute('process-ident')

    '''

    def __init__(self, service):
        policy_file = os.path.join(POLICY_DIR, service)
        if not os.path.exists(policy_file):
            # fallback to policy without specific argument set (if any)
            policy_file = os.path.join(POLICY_DIR, service.split('+')[0])

        #: service name
        self.service = service

        #: list of PolicyLine objects
        self.policy_rules = []
        try:
            self.load_policy_file(policy_file)
        except OSError as e:
            raise AccessDenied(
                'failed to load {} file: {!s}'.format(e.filename, e))

    def load_policy_file(self, path):
        ''' Load policy file and append rules to :py:attr:`policy_rules`

        :param path: file to load
        '''
        with open(path) as policy_file:
            for lineno, line in zip(itertools.count(start=1),
                    policy_file.readlines()):
                line = line.strip()
                if not line:
                    # skip empty lines
                    continue
                if line[0] == '#':
                    # skip comments
                    continue
                if line.startswith('$include:'):
                    include_path = line.split(':', 1)[1]
                    # os.path.join will leave include_path unchanged if it's
                    # already absolute
                    include_path = os.path.join(POLICY_DIR, include_path)
                    self.load_policy_file(include_path)
                else:
                    self.policy_rules.append(PolicyRule(line, path, lineno))

    def find_matching_rule(self, system_info, source, target):
        ''' Find the first rule matching given arguments '''

        for rule in self.policy_rules:
            if rule.is_match(system_info, source, target):
                return rule
        raise AccessDenied('no matching rule found')


    def collect_targets_for_ask(self, system_info, source):
        ''' Collect targets the user can choose from in 'ask' action

        Word 'targets' is used intentionally instead of 'domains', because it
        can also contains $dispvm like keywords.
        '''
        targets = set()

        # iterate over rules in reversed order to easier handle 'deny'
        # actions - simply remove matching domains from allowed set
        for rule in reversed(self.policy_rules):
            if rule.is_match_single(system_info, rule.source, source):
                if rule.action == Action.deny:
                    targets -= set(rule.expand_target(system_info))
                else:
                    if rule.override_target is not None:
                        override_target = rule.expand_override_target(
                            system_info, source)
                        if verify_target_value(system_info, override_target):
                            targets.add(rule.override_target)
                    else:
                        targets.update(rule.expand_target(system_info))

        # expand default DispVM
        if '$dispvm' in targets:
            targets.remove('$dispvm')
            if system_info['domains'][source]['default_dispvm'] is not None:
                dispvm = '$dispvm:' + \
                    system_info['domains'][source]['default_dispvm']
                if verify_target_value(system_info, dispvm):
                    targets.add(dispvm)

        return targets

    def evaluate(self, system_info, source, target):
        ''' Evaluate policy

        :raise AccessDenied: when action should be denied unconditionally

        :return tuple(rule, considered_targets) - where considered targets is a
        list of possible targets for 'ask' action (rule.action == Action.ask)
        '''
        rule = self.find_matching_rule(system_info, source, target)
        if rule.action == Action.deny:
            raise AccessDenied(
                'denied by policy {}:{}'.format(rule.filename, rule.lineno))

        if rule.override_target is not None:
            override_target = rule.expand_override_target(system_info, source)
            if not verify_target_value(system_info, override_target):
                raise AccessDenied('invalid target= value in {}:{}'.format(
                    rule.filename, rule.lineno))
            actual_target = override_target
        else:
            actual_target = target

        if rule.action == Action.ask:
            if rule.override_target is not None:
                targets = [actual_target]
            else:
                targets = list(
                    self.collect_targets_for_ask(system_info, source))
            if not targets:
                raise AccessDenied(
                    'policy define \'ask\' action at {}:{} but no target is '
                    'available to choose from'.format(
                        rule.filename, rule.lineno))
            return PolicyAction(self.service, source, rule.default_target,
                rule, target, targets)
        elif rule.action == Action.allow:
            if actual_target == '$default':
                raise AccessDenied(
                    'policy define \'allow\' action at {}:{} but no target is '
                    'specified by caller or policy'.format(
                        rule.filename, rule.lineno))
            return PolicyAction(self.service, source,
                actual_target, rule, target)
        else:
            # should be unreachable
            raise AccessDenied(
                'invalid action?! {}:{}'.format(rule.filename, rule.lineno))


class QubesMgmtException(Exception):
    ''' Exception returned by qubesd '''
    def __init__(self, exc_type):
        super(QubesMgmtException, self).__init__()
        self.exc_type = exc_type


def qubesd_call(dest, method, arg=None, payload=None):
    try:
        client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_socket.connect(QUBESD_INTERNAL_SOCK)
    except IOError:
        # TODO:
        raise

    # src, method, dest, arg
    for call_arg in ('dom0', method, dest, arg):
        if call_arg is not None:
            client_socket.sendall(call_arg.encode('ascii'))
        client_socket.sendall(b'\0')
    if payload is not None:
        client_socket.sendall(payload)

    client_socket.shutdown(socket.SHUT_WR)

    return_data = client_socket.makefile('rb').read()
    if return_data.startswith(b'0\x00'):
        return return_data[2:]
    elif return_data.startswith(b'2\x00'):
        (_, exc_type, _traceback, _format_string, _args) = \
            return_data.split(b'\x00', 4)
        raise QubesMgmtException(exc_type.decode('ascii'))
    else:
        raise AssertionError(
            'invalid qubesd response: {!r}'.format(return_data))


def get_system_info():
    ''' Get system information

    This retrieve information necessary to process qrexec policy. Returned
    data is nested dict structure with this structure:

    - domains:
      - <domain name>:
        - tags: list of tags
        - type: domain type
        - dispvm_allowed: should DispVM based on this VM be allowed
        - default_dispvm: name of default AppVM for DispVMs started from here

    '''

    system_info = qubesd_call('dom0', 'internal.GetSystemInfo')
    return json.loads(system_info.decode('utf-8'))
