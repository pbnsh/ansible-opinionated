# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
name: inventory
short_description: opinionated inventory
description:
  - Flat inventory.
options:
    plugin:
        description: Name of the plugin.
        choices: ['pbn.op.inventory']
        required: True
    root_dir:
        description:
          - Name of the directory which is the root of ansible repository,
          - usually contains ansible.cfg, playbooks and roles directories.
        required: True
        type: string
        env:
          - name: ANSIBLE_OP_INVENTORY_ROOT_DIR
        ini:
          - section: pbn_op_inventory
            key: root_dir
    identifier_prefix:
        description:
          - Prefix used to denote internal vars, defaults to 'pbn'.
        type: string
        default: pbn
        env:
          - name: ANSIBLE_OP_INVENTORY_IDENTIFIER_PREFIX
        ini:
          - section: pbn_op_inventory
            key: IDENTIFIER_PREFIX
    inventory_var_files:
        description:
          - List of variable files that will searched up the tree in inventory.
          - Will fail if any of the files are not found.
        default: ['_site.yml', '_env.yml']
        type: list
        elements: string
        env:
          - name: ANSIBLE_OP_INVENTORY_INVENTORY_VAR_FILES
        ini:
          - section: pbn_op_inventory
            key: inventory_var_files
    var_dirs:
        description:
          - List of directories defined as $identifier_prefix_$name which contain
          - values of $identifier_prefix_$name as yaml files.
        type: list
        default: []
        elements: string
        env:
          - name: ANSIBLE_OP_INVENTORY_VAR_DIRS
        ini:
          - section: pbn_op_inventory
            key: var_dirs
    append_dns_domain:
        description:
          - Appends $identifier_prefix_dns_domain if hostnames are not fqdn.
          - $identifier_prefix_dns_domain must be present in inventory, usually defined
          - in _common.yml for example "pbn_dns_domain {{ pbn_site }}.{{ pbn_env }}.pbn.corp"
        type: bool
        default: false
        env:
          - name: ANSIBLE_OP_INVENTORY_APPEND_DNS_DOMAIN
        ini:
          - section: pbn_op_inventory
            key: append_dns_domain
"""

import copy
from pathlib import Path

import jinja2

from ansible.plugins.inventory import (
    BaseInventoryPlugin,
    expand_hostname_range,
    detect_range,
)
from ansible.parsing.dataloader import DataLoader
from ansible.utils.display import Display
from ansible.errors import AnsibleError, AnsibleParserError, AnsibleFileNotFound
from ansible.plugins.filter.core import FilterModule
from ansible.template import is_possibly_template
from ansible.module_utils.common.text.converters import to_text

display = Display()
data_loader = DataLoader()


def get_root_path(path: Path, root_dir: str) -> Path:
    """
    Traverses up the path until root_dir is found.
    """
    while str(path) != path.root:
        if path.name == root_dir:
            return path
        path = path.parent
    raise AnsibleParserError(f"Failed to find root_dir: {root_dir}, path: {path}")


def get_contents(path: Path) -> dict:
    return data_loader.load_from_file(str(path)) or {}


def parse_path(path: Path, include=None) -> dict:
    """
    Searches for .yml, .yaml files at path, skips non yaml and files starting
    with underscore.
    """
    if include is None:
        include = []

    display.vvv(to_text(f"pbn_op_inventory: path: {str(path)}"))
    for item in path.glob("*"):
        if item.suffix not in [".yml", ".yaml"] or item.stem.startswith("_"):
            display.vvv(to_text(f"pbn_op_inventory: skip: {item}"))
            continue
        if include and item.stem not in include:
            display.vvv(to_text(f"pbn_op_inventory: excluded: {item}"))
            continue
        display.vvv(to_text(f"pbn_op_inventory: read: {item}"))
        yield item.stem, get_contents(item)


def get_inventory(
    path: Path, var_files: list, root_dir: str, raise_on_missing=True
) -> dict:
    """
    Searches for var_files starting from path and stops at root_dir.
    """
    var_files_copy = copy.copy(var_files)
    var_filepaths = []
    while path.name != root_dir and str(path) != path.root:
        for idx, f in enumerate(var_files_copy):
            variable_filepath = Path(path / f)
            if variable_filepath.is_file():
                var_filepaths.append(variable_filepath)
                var_files_copy.pop(idx)
        path = path.parent

    if var_files_copy and raise_on_missing:
        raise AnsibleParserError(f"failed to find: {var_files}, aborting")

    res = {}
    for var_filename in var_files:
        display.vvv(to_text(f"pbn_op_inventory: inventory: {str(path / var_filename)}"))
        for variable_filepath in var_filepaths:
            if variable_filepath.name == var_filename:
                contents = get_contents(variable_filepath)
                res.update(contents)
    return res


def get_playbook(path: Path, identifier_prefix, include=None) -> dict:
    """
    Parses playbooks, users $identifier_prefix_role as a role identifier.
    """
    res = {}
    for role_filename, contents in parse_path(path, include):
        role_name, role_vars = None, None
        for item in contents:
            if "hosts" in item:
                role_name = item.get("hosts")
            if "vars" in item:
                role_name = item["vars"].get(f"{identifier_prefix}_role")
            if role_name is None:
                continue
            role_vars = item.get("vars", {}) or {}
        if role_name is None:
            raise AnsibleParserError(
                f"Failed to determine role name from {role_filename}."
            )
        if role_filename != role_name:
            raise AnsibleParserError(
                f"Playbook name role var mismatch, playbook: {role_filename} "
                f"role var: {role_name}."
            )
        res[role_name] = role_vars
        # if we got role from hosts, role might not be defined via vars
        res[role_name][f"{identifier_prefix}_role"] = role_name
    return res


def get_role_defaults(path: Path, playbook_vars: dict) -> dict:
    """
    Parses roles/$role/defaults/main.yml, if base_role is defined in
    playbook_vars parses roles/$base_role/defaults/main.yml
    """
    res = {}
    for role_name, role_vars in playbook_vars.items():
        defaults = path / role_name / "defaults" / "main.yml"
        if "base_role" in role_vars:
            defaults = path / role_vars["base_role"] / "defaults" / "main.yml"
        try:
            display.vvv(to_text(f"pbn_op_inventory: defaults: {str(path / defaults)}"))
            res[role_name] = get_contents(defaults)
        except AnsibleFileNotFound:
            pass
    return res


def role_inventory_override(role_vars: dict, identifier_prefix: str) -> dict:
    """
    Overrides inventory variables with role_default inventory overrides.
    """
    inventory_override = role_vars.get(f"{identifier_prefix}_inventory_override", {})
    if not inventory_override:
        return {}
    common = f"{identifier_prefix}_common"
    res = inventory_override.get(common, {})
    for k, v in inventory_override.items():
        if k not in role_vars:
            continue
        if k == common:
            continue
        if role_vars[k] not in v:
            continue
        res |= inventory_override[k][role_vars[k]]
    return res


def template_vars(jinja_env: jinja2, role_vars: dict) -> dict:
    """
    Templates all knows variables.
    """
    to_template = [
        k for k, v in role_vars.items() if is_possibly_template(v, jinja_env)
    ]
    if not to_template:
        return role_vars

    no_template = {k: v for k, v in role_vars.items() if k not in to_template}
    for k in to_template:
        try:
            role_vars[k] = jinja_env.from_string(role_vars[k]).render(**no_template)
        except (
            jinja2.exceptions.UndefinedError,
            jinja2.exceptions.TemplateAssertionError,
            jinja2.exceptions.TemplateSyntaxError,
            TypeError,
        ):
            pass

    return role_vars


def construct_hosts(role_vars: dict, jinja_env: jinja2.Environment) -> dict:
    """
    Templates any host vars if found and construct hosts from ansible
    ranges of hosts format.
    """
    hosts = role_vars.get("hosts") or {}
    if not hosts:
        return {}
    if not isinstance(hosts, dict):
        raise ValueError(f"failed to parse hosts key: {hosts}")

    res = {}
    templated_vars = template_vars(jinja_env, role_vars)
    for host, host_vars in hosts.items():
        hostname = host
        if is_possibly_template(host, jinja_env):
            hostname = jinja_env.from_string(host).render(**templated_vars)
        ranged_hostnames = [hostname]
        if detect_range(hostname):
            try:
                ranged_hostnames = expand_hostname_range(hostname)
            except AnsibleError:
                pass
        for item in ranged_hostnames:
            res[item] = {}
            if host_vars is not None and isinstance(host_vars, dict):
                res[item] = host_vars
    return res


def get_vars(path: Path, directories: list) -> dict:
    """
    Looks for var files in ansible-root/vars/$identifier_prefix_$dir_name/$var_value_defined
    in inventory.
    """
    if not path.is_dir():
        return {}

    res = {}
    for subdirectory in path.iterdir():
        display.vvv(to_text(f"pbn_op_inventory: get_vas: {str(subdirectory)}"))
        if not subdirectory.is_dir():
            continue
        if subdirectory.stem not in directories:
            continue
        for item in subdirectory.iterdir():
            if not item.is_file():
                continue
            if item.suffix not in [".yml", ".yaml"]:
                continue
            display.vvv(to_text(f"pbn_op_inventory: vars: {str(subdirectory / item)}"))
            contents = get_contents(item)
            res.setdefault(subdirectory.stem, {}).update({item.stem: contents})
    return res


class InventoryModule(BaseInventoryPlugin):
    NAME = "op.inventory"

    def verify_file(self, path):
        """
        Validates if inventory source can be used by this plugin.
        """
        valid = False
        if super(InventoryModule, self).verify_file(path):
            if path.endswith("_inventory.yml"):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):
        super(InventoryModule, self).parse(inventory, loader, path, cache)
        self._read_config_data(path)
        jinja_env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
        for k, v in FilterModule().filters().items():
            jinja_env.filters.update({k: v})

        # ansible sets `path` as absolute path to `_inventory_yml`
        inventory_path = Path(path).parent
        root_dir = self.get_option("root_dir")
        identifier_prefix = self.get_option("identifier_prefix")
        append_dns_domain = self.get_option("append_dns_domain")

        root_path = get_root_path(inventory_path, root_dir)

        common_vars = get_inventory(
            inventory_path,
            ["_common.yaml", "_common.yml"],
            root_path.stem,
            raise_on_missing=False,
        )
        inventory_vars = get_inventory(
            inventory_path, self.get_option("inventory_var_files"), root_path.stem
        )
        group_vars = dict(parse_path(inventory_path))
        roles = list(group_vars.keys())
        playbook_vars = get_playbook(root_path / "playbooks", identifier_prefix, roles)
        role_defaults = get_role_defaults(root_path / "roles", playbook_vars)
        var_dirs = get_vars(root_path / "vars", self.get_option("var_dirs"))

        for role in roles:
            display.vvv(to_text(f"pbn_op_inventory: role: {role}"))
            self.inventory.add_group(role)
            role_vars = role_defaults.get(role, {})
            role_vars |= common_vars
            role_group_inventory_vars = {
                **role_vars,
                **group_vars.get(role, {}),
                **inventory_vars,
            }
            for identifier_var, _vars in var_dirs.items():
                if identifier_var not in role_group_inventory_vars.keys():
                    continue
                identifier_var_value = role_group_inventory_vars[identifier_var]
                if identifier_var_value not in _vars:
                    continue
                role_vars |= _vars[identifier_var_value]

            role_vars |= inventory_vars
            role_vars |= role_inventory_override(role_vars, identifier_prefix)
            role_vars |= group_vars.get(role, {})
            role_vars |= playbook_vars.get(role, {})
            for k, v in role_vars.items():
                if k in ["hosts", f"{identifier_prefix}_inventory_override"]:
                    continue
                self.inventory.set_variable(role, k, v)

            try:
                hosts = construct_hosts(role_vars, jinja_env)
                display.vvv(to_text(f"pbn_op_inventory: hosts: {hosts}"))
            except ValueError as e:
                raise AnsibleParserError(f"role: {role}, {e}")

            dns_domain = role_vars.get(
                f"{identifier_prefix}_dns_domain",
                f"{identifier_prefix}_dns_domain_not_set",
            )
            for host, host_vars in hosts.items():
                hostname = host
                if append_dns_domain and len(hostname.split(".")) == 1:
                    hostname = f"{hostname}.{dns_domain}"
                self.inventory.add_host(hostname, group=role)
                for k, v in host_vars.items():
                    if not v:
                        continue
                    self.inventory.set_variable(hostname, k, v)
