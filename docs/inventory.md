# Inventory

Flat inventory, allows to define Ansible inventory as follows:

```
ansible-config
├── ansible.cfg
├── playbooks
│   └── webserver.yml
├── roles
│   ├── webserver
│   │   └── tasks
│   │       └── main.yml
└── sites
    ├── _common.yml
    └── eu-central-1
        ├── _site.yml
        ├── dev
        │   ├── _env.yml
        │   ├── _inventory.yml
        │   └── webserver.yml
        └── prod
            ├── _env.yml
            ├── _inventory.yml
            └── webserver.yml
```

From the example above, variables defined in `_common.yml` are shared in all
sites and environments, variables defined in `_site.yml` are shared for that
site and all environments within site, and variables defined in `_env.yml` are
used in that environment within a site.

The `_common.yml|yaml` file is always parsed, `['_site.yml', '_env.yml']` 
variables are configurable via `inventory_var_files` config option. 

Running ansible against `webserver` role in `eu-central/dev` would look like:

```
ansible-playbook -i sites/eu-central-1/prod playbooks/webserver.yml
```

Playbook acts as a single entry point for `webserver` role and can be defined in
two ways:

1. generic playbook:
    ```
    ---
    - hosts: webserver
      tasks:
        - debug:
    ```

2. wrapper (_wrapper.yml) + role playbook (webserver.yml):
    ```
    ---
    - hosts: {{ pbn_role }}
      tasks:
        - debug:
    ```

    ```
    ---
    - import_playbook: _wrapper.yml
      vars:
        pbn_role: webserver
    ```

Inventory relies on _identifier variables_ which represent uniqueness among
sites/environments and roles. When "generic playbook" is used, role
defined in `hosts` will be added to inventory as `pbn_role`. If wrapper playbook
is used, `pbn_role` must be passed explicitly. The identifier_prefix, which
defaults to `pbn` can be configured via ansible.cfg or environment variable.

Each inventory file, apart from common, should contain:

* `_site.yml`
    ```
    ---
    pbn_site: eu-central-1
    ```

* `_env.yml`
    ```
    ---
    pbn_env: dev
    ```

In addition to inventory, role defaults are also parsed and added as `host_vars`
at early stage, this differs from default Ansible behaviour:

> Tasks in each role see their own role's defaults. Tasks defined outside of a role see the last role's defaults.

Having role defaults early makes it possible to override any role that is
executed before parent role and is useful when parent role consist of many
smaller roles.
`hosts` can also be defined in role defaults, and accepts inventory variables
as part of the hostname, for example `webserver[01:02].{{ pbn_site }}.{{ pbn_env }}.pbn.corp`,
this avoids repetition and is useful with static hosts that should exist in every
site. Note, variables that are used in hostname templating must be defined
in inventory.

## Inventory variable precedence from least to most

This inventory plugin
replaces [Ansible variable precedence](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html#understanding-variable-precedence)
from number 2 to 10 with:

```
1. role defaults                      - roles/$role/defaults/main.yml
2. common iventory vars               - sites/_common.yml
2. vars directory                     - vars/$var_dir/$identifier_var_value.yml
3. iventory variables                 - inventory variable files merged in defined order
4. role defaults inventory overrides  - roles/$role/defaults/main.yml (pbn_inventory_override dictionary)
5. inventory role group vars          - sites/eu-central-1/prod/$role.yml
6. playbook vars                      - playbooks/$role.yml
```

## Config options

| Name                  | Type        | Description                                                                                                             | Required |
|-----------------------|-------------|-------------------------------------------------------------------------------------------------------------------------|:--------:|
| `root_dir`            | `str`       | Name of ansible root directory, usually root of git repo where ansible configs are stored.                              |   Yes    |
| `role_source`         | `str`       | One of `inventory` (default) or `playbooks`, see [below](#role_source).                                                 |    No    |
| `identifier_prefix`   | `str`       | Prefix used in identifier variables, defaults to `pbn`.                                                                 |    No    |
| `inventory_var_files` | `list(str)` | Inventory variable files, that will be merged in defined order, defaults to: `['_site.yml', '_env.yml']`.               |    No    |
| `var_dirs`            | `list(str)` | Names of directories defined under root_dir/vars which hold addition inventory variables, see [below](#var_dirs).       |    No    |
| `append_dns_domain`   | `bool`      | Toggle if hostname should be appended with `pbn_dns_domain` when hostname is not fqdn, see [below](#append_dns_domain). |    No    |

All the options defined above can be set via env vars, for example `ANSIBLE_OP_INVENTORY_ROLE_SOURCE`.

Minimal config:

```
[defaults]
inventory_ignore_patterns = '^(?!_inventory\.yml|_inventory\.yaml).*$'

[pbn_op_inventory]
root_dir = ansible-config
```

**NOTE:** inventory_ignore_patterns must be set in `[defaults]` section,
see [Handling multiple inventories](#handling-multiple-inventories) below.

### role_source

When `inventory` is set as a role_source, pbn_op_inventory will return
only those roles that exist in passed inventory.

When `playbooks` is set as a role_source, pbn_op_inventory will take roles from
playbooks, look for `hosts` in `roles/$role/defaults.yml` and return only those
with defined hosts.

See [examples](https://github.com/pbnsh/ansible-opinionated/tree/master/examples)
directory.

### var_dirs

In the situation where you have multiple environments, or you have variables
that are specific to a subset of sites/envs you would have to define them in every
`sites/$site/$env/_env.yml`. Rather than copy/pasting the same variables into
each `_env.yml` file, in every site, you can configure then with `var_dirs`.

The `var_dirs` option takes a list directory names and merges them in defined
order.

For example, when vars_dirs is set to: `['pbn_provider', 'pbn_env']` and vars
directory in is configured as shown below, pbn_op_inventory will check if
directory name exist in inventory vars, if found, will take value of directory
from inventory and lookup a file under `vars/$dir_name/$inventory_value.yml`.

```
ansible-config
│
...
└── vars
    ├── pbn_provider
    │   ├── aws.yml
    │   └── proxmox.yml
    └── pbn_env
        ├── dev.yml
        └── prod.yml
```

This allows to load additional inventory variables and avoids unnecessary clutter
in `_common.yml`.

### append_dns_domain

When `append_dns_domain` is set to true and hosts in inventory are not fqdn,
pb_op_inventory will append value of `pbn_dns_domain` to every hostname.

`pbn_dns_domain` should be set in sites/_common.yml.

## Role defaults inventory override

Role defaults inventory override works in similar manner as `var_dirs` and
allows to override parts of inventory from role defaults.

For example `_common.yml` sets `ntp_servers`, for all roles in every site/env:

```
---
ntp_servers:
  - 0.pool.ntp.org
  - 1.pool.ntp.org
```

And `sites/eu-central-1/dev/_env.yml` sets `dns_servers` for all roles in that site/env:

```
---
dns_servers:
  - 10.1.2.3
  - 10.1.2.4
```

Because role defaults are lower priority than inventory vars, it's not possible
to override `ntp_servers` or `dns_servers` from role defaults.

`pbn_inventory_override` solves this issue and can be configured in
`roles/webserver/defaults/main.yml` as:

```
---
pbn_inventory_override:
  pbn_common:
    ntp_servers:
      - 0.debian.pool.ntp.org
  pbn_env:
    dev:
      dns_servers:
        - 1.1.1.1
```

In example above, `webserver` role will use `0.debian.pool.ntp.org` for ntp_servers
regardless of site/env and will use `1.1.1.1` as a dns server in all dev
environments in every site.

## Handling multiple inventories

When directory is passed as an inventory to ansible-playbook, Ansible treats
every YAML file as an inventory source and will output warnings as it's unable
to parse .yml files as inventory, this is expected behaviour.

To avoid inventory warnings, inventory_ignore_patterns must be configured
in `[defaults]` section of ansible.cfg, for example:

```
[defaults]
inventory_ignore_patterns = '^(?!_inventory\.yml|_inventory\.yaml).*$'
```

This tells ansible to ignore every file that doesn't match the pattern inventory source.

To use multiple inventories, modify inventory_ignore_patterns to include all
files that should be considered an inventory source: `'^(?!_01_openstack\.yml|_02_inventory\.yml).*$'`

## Creating your first inventory

1. Ensure that ansible.cfg contains:
    ```
    [defaults]
    inventory_ignore_patterns = '^(?!_inventory\.yml).*$'

    [pbn_op_inventory]
    root_dir = ansible-config
    ```

2. Crease site:
    ```
    ANSIBLE_ROOT+ansible-config
    SITE_NAME=eu-west-1
    ENV=dev

    mkdir -p "${ANSIBLE_ROOT}/sites/${SITE_NAME}/${ENV}"
    tee "${ANSIBLE_ROOT}/sites/_common.yml" <<EOF > /dev/null
    ---
    EOF

    tee "${ANSIBLE_ROOT}/sites/${SITE_NAME}/_site.yml" <<EOF > /dev/null
    ---
    pbn_site: "${SITE_NAME}"
    EOF

    tee "${ANSIBLE_ROOT}/sites/${SITE_NAME}/${ENV}/_env.yml" <<EOF > /dev/null
    ---
    pbn_env: "${ENV}"
    EOF

    tee "${ANSIBLE_ROOT}/sites/${SITE_NAME}/${ENV}/_inventory.yml" <<EOF > /dev/null
    ---
    plugin: pbn.op.inventory
    EOF
    ```

See [examples](https://github.com/pbnsh/ansible-opinionated/tree/master/examples) directory for

