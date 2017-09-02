:py:mod:`qubes.policy` -- Qubes RPC policy
==========================================

Every Qubes domain can trigger various RPC services, but if such call would be
allowed depends on Qubes RPC policy (qrexec policy in short).

Qrexec policy format
--------------------

Policy consists of a file, which is parsed line-by-line. First matching line
is used as an action.

Each line consist of three values separated by white characters (space(s), tab(s)):

1. Source specification, which is one of:

  - domain name
  - `$anyvm` - any domain
  - `$tag:some-tag` - VM having tag `some-tag`
  - `$type:vm-type` - VM of `vm-type` type, available types:
    AppVM, TemplateVM, StandaloneVM, DispVM

2. Target specification, one of:

  - domain name
  - `$anyvm` - any domain, excluding dom0
  - `$tag:some-tag` - domain having tag `some-tag`
  - `$type:vm-type` - domain of `vm-type` type, available types:
    AppVM, TemplateVM, StandaloneVM, DispVM
  - `$default` - used when caller did not specified any VM
  - `$dispvm:vm-name` - _new_ Disposable VM created from AppVM `vm-name`
  - `$dispvm:$tag:some-tag` - _new_ Disposable VM created from AppVM tagged with `some-tag`
  - `$dispvm` - _new_ Disposable VM created from AppVM pointed by caller
    property `default_dispvm`, which defaults to global property `default_dispvm`
  - `$adminvm` - Admin VM aka dom0

  Dom0 can only be matched explicitly - either as `dom0` or `$adminvm` keyword.
  None of `$anyvm`, `$tag:some-tag`, `$type:AdminVM` will match.

3. Action and optional action parameters, one of:

  - `allow` - allow the call, without further questions; optional parameters:

    - `target=` - override caller provided call target -
      possible values are: domain name, `$dispvm` or `$dispvm:vm-name`
    - `user=` - call the service using this user, instead of the user
      pointed by target VM's `default_user` property
  - `deny` - deny the call, without further questions; no optional
    parameters are supported
  - `ask` - ask the user for confirmation; optional parameters:

    - `target=` - override user provided call target
    - `user=` - call the service using this user, instead of the user
      pointed by target VM's `default_user` property
    - `default_target=` - suggest this target when prompting the user for
      confirmation

Alternatively, a line may consist of a single keyword `$include:` followed by a
path. This will load a given file as its content would be in place of
`$include` line. Relative paths are resolved relative to
`/etc/qubes-rpc/policy` directory.

Evaluating `ask` action
-----------------------

When qrexec policy specify `ask` action, the user is asked whether the call
should be allowed or denied. In addition to that, user also need to choose
target domain. User have to choose from a set of targets specified by the
policy. Such set is calculated using the algorithm below:

1. If `ask` action have `target=` option specified, only that target is
considered. A prompt window will allow to choose only this value and it will
also be pre-filled value.

2. If no `target=` option is specified, all rules are evaluated to see what
target domains (for a given source domain) would result in `ask` or `allow`
action. If any of them have `target=` option set, that value is used instead of
the one specified in "target" column (for this particular line). Then the user
is presented with a confirmation dialog and an option to choose from those
domains. 

3. If `default_target=` option is set, it is used as
suggested value, otherwise no suggestion is made (regardless of calling domain
specified any target or not).



Module contents
---------------

.. automodule:: qubespolicy
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et
