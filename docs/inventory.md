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

Running ansible again webserver role would look like:
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
defined in `hosts` will be added to inventory as `pbn_role` variable.
If wrapper playbook is used, `pbn_role` must be passed explicitly.
The identifier_prefix, which defaults to `pbn` can be changed in ansible.cfg
or by `ANSIBLE_OP_INVENTORY_IDENTIFIER_PREFIX` environment variable.

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

Parsing role defaults early makes it possible to override any role that is
executed before parent role and is useful when parent role consist of many
smaller roles.
`hosts` can also be defined in role defaults, and accepts inventory variables
as part of the hostname, for example `webserver[01:02].{{ pbn_site }}.{{ pbn_env }}.pbn.corp`,
this avoids repetition and is useful with static hosts that should exist in every
site. Note, variables that are used in hostname templating must exist in inventory.

Checkout [examples](https://github.com/pbnsh/ansible-opinionated/tree/master/examples) directory for pre-configured inventory.

## Inventory variable precedence from least to most (merge order)

This inventory plugin replaces [Ansible variable precedence](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html#understanding-variable-precedence)
from number 2 to 10 with:

```
1. role defaults                      - roles/$role/defaults/main.yml
2. common iventory vars               - sites/_common.yml
2. vars directory                     - vars/$var_dir/$identifier_var_value.yml
3. iventory variables                 - inventory variable files merged in defined order (_site.yml, _env.yml)
4. role defaults inventory overrides  - roles/$role/defaults/main.yml (pbn_inventory_override dictionary)
5. inventory role group vars          - sites/eu-central-1/prod/$role.yml
6. playbook vars                      - playbooks/$role.yml
```

## Config options

| Name                  | Type        | Description                                                                                                             | Required |
|-----------------------|-------------|-------------------------------------------------------------------------------------------------------------------------|:--------:|
| `root_dir`            | `str`       | Name of ansible root directory, usually root of git repo where ansible configs are stored.                              |   Yes    |
| `identifier_prefix`   | `str`       | Prefix used in identifier variables, defaults to `pbn`.                                                                 |    No    |
| `inventory_var_files` | `list(str)` | Inventory variable files, that will be merged in defined order, defaults to: `['_site.yml', '_env.yml']`.               |    No    |
| `var_dirs`            | `list(str)` | Names of directories defined under root_dir/vars which hold addition inventory variables, see [below](#var_dirs).       |    No    |
| `append_dns_domain`   | `bool`      | Toggle if hostname should be appended with `pbn_dns_domain` when hostname is not fqdn, see [below](#append_dns_domain). |    No    |

All the options defined above can be set via env vars, for example `ANSIBLE_OP_INVENTORY_ROLE_SOURCE`.

**NOTE:** inventory_ignore_patterns must be set in `[defaults]` section,
see [Handling multiple inventories](#handling-multiple-inventories) below.

## Usage

1. Set environment variables which will be used by all steps below:
   ```
   ROLE=webserver
   ANSIBLE_ROOT=ansible-config
   SITE_NAME=eu-west-1
   ENV=dev
   ```

2. Create ansible directory and ansible.cfg
    ```
    mkdir "${ANSIBLE_ROOT}" && cd $_
    cat > ansible.cfg <<EOF
    [defaults]
    collections_path = ./collections
    roles_path = ./roles
    inventory_ignore_patterns = '^(?!_inventory\.yml|_inventory\.yaml).*$'

    [pbn_op_inventory]
    root_dir = "${ANSIBLE_ROOT}"
    append_dns_domain = True
    EOF
    ```

3. Install ansible-opinionated collections
   ```
   cat > requirements.yml <<EOF
   ---
   collections:
     - name: https://github.com/pbnsh/ansible-opinionated.git
       type: git
       version: "v0.0.5"
   EOF

   ansible-galaxy collection install -p ./collections -r requirements.yml
   ```

4. Create role:
    ```
    mkdir -p "roles/${ROLE}/tasks"
    cat > "roles/${ROLE}/tasks/main.yml" << EOF
    ---
    - debug:
        msg: |
          pbm_site {{ pbn_site }}
          pbn_env {{ pbn_env }}
          role_default_var {{ role_default_var }}
          role_inventory_var {{ role_inventory_var }}
    EOF
    ```

    ```
    mkdir -p "roles/${ROLE}/defaults"
    cat > "roles/${ROLE}/defaults/main.yml" << EOF
    ---
    role_default_var: default_variable
    EOF
    ```

5. Create playbook
    ```
    mkdir playbooks
    cat > "playbooks/${ROLE}.yml" << EOF
    - hosts: webserver
      tasks:
        - include_role:
            name: webserver
      connection: local
    EOF
    ```
    **MOTE:** `connection: local` is only used in example and should be omitted
    when used in actual inventory.

6. Crease site:
    ```
    mkdir -p "sites/${SITE_NAME}/${ENV}"
    cat > "sites/_common.yml" <<EOF
    ---
    pbn_dns_domain: example.com
    EOF

    cat > "sites/${SITE_NAME}/_site.yml" <<EOF
    ---
    pbn_site: "${SITE_NAME}"
    EOF

    cat > "sites/${SITE_NAME}/${ENV}/_env.yml" <<EOF
    ---
    pbn_env: "${ENV}"
    EOF

    cat > "sites/${SITE_NAME}/${ENV}/_inventory.yml" <<EOF
    ---
    plugin: pbn.op.inventory
    EOF
    ```

7. Create site role vars:
    ```
    cat > "sites/${SITE_NAME}/${ENV}/webserver.yml" <<EOF
    ---
    hosts:
      webserver[01:02]:
        ansible_host: 127.0.0.1
    role_inventory_var: inventory_variable
    EOF
    ```

8. Run ansible-playbook
   ```
   ansible-playbook -i sites/eu-west-1/dev playbooks/webserver.yml --list-hosts
   ```

---

### var_dirs

In the situation where you have multiple environments, or you have variables
that are specific to a subset of sites/envs you would have to define them in every
`sites/$site/$env/_env.yml`. Rather than copy/pasting the same variables into
each `_env.yml` file, in every site, you can configure then with `var_dirs`.

The `var_dirs` option takes a list directory names and merges them in defined
order.

For example, when vars_dirs is set to: `['pbn_provider', 'pbn_env']` and vars
directory is configured as shown below, pbn_op_inventory will check if
directory name exist, if found, will take value `pbn_provider` or `pbn_env`
lookup a file under `vars/$dir_name/$inventory_value.yml`.

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
pbn_op_inventory will append value of `pbn_dns_domain` to every hostname.

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

