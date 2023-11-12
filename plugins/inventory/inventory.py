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
    role_source:
        description:
          - Source of roles that are considered part of inventory.
          - When set to 'inventory', will use inventory/$site/$env/ as a source for groups.
          - When set to 'playbooks', will use playbooks/ directory as a source for groups.
        type: string
        default: inventory
        choices: ['inventory', 'playbooks']
        env:
          - name: ANSIBLE_OP_INVENTORY_ROLE_SOURCE
        ini:
          - section: pbn_op_inventory
            key: role_source
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
        default: ['_common.yml', '_site.yml', '_env.yml']
        type: list
        elements: string
        env:
          - name: ANSIBLE_OP_INVENTORY_INVENTORY_VAR_FILES
        ini:
          - section: pbn_op_inventory
            key: inventory_var_files
    var_dirs:
        description:
          - List of directories of additional vars that will me merged in defined order.
          - Used to load additional variables,inventory contains pbn_env variable
          - with value dev and if ansible_root/vars/pbn_env/dev.yml exist, it
          - will be processed.
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
from ansible.errors import AnsibleParserError, AnsibleFileNotFound
from ansible.plugins.filter.core import FilterModule
from ansible.template import is_possibly_template
from ansible.module_utils.common.text.converters import to_text

display = Display()
data_loader = DataLoader()


def get_root_path(path: Path, root_dir: str) -> Path:
    """
    Traverses up the path until root_dir is found.

    :param path: path where to start search from
    :param root_dir: path where end search
    :return: absolute path to root_dir
    """

    while str(path) != path.root:
        if path.name == root_dir:
            return path
        path = path.parent
    raise AnsibleParserError(f"Failed to find root_dir: {root_dir}, path: {path}")


def parse_path(path: Path, include=None) -> dict:
    """
    Searches for .yml, .yaml files at path, skips non yaml and files starting
    with underscore.

    :param path: path where to search for .yml, .yaml files
    :param include: list of files without extension to return if found
    :return: dict {"file_name_without_extension": "contents_of_the_file"}
    """
    if include is None:
        include = []

    display.vvv(to_text(f"pbn_op_inventory: path {str(path)}"))
    for item in path.glob("*"):
        if item.suffix not in [".yml", ".yaml"] or item.stem.startswith("_"):
            display.vvv(to_text(f"pbn_op_inventory: skipped {item}"))
            continue
        if include and item.stem not in include:
            display.vvv(to_text(f"pbn_op_inventory: excluded {item}"))
            continue
        contents = data_loader.load_from_file(str(item))
        if contents is None:
            display.vvv(to_text(f"pbn_op_inventory: no contents {item}"))
            contents = {}
        display.vvv(to_text(f"pbn_op_inventory: yield {item}"))
        yield item.stem, contents


def get_playbook(path: Path, identifier_prefix, include=None) -> dict:
    """
    Parses playbooks, users $identifier_prefix_role as a role identifier.

    :param path: path where to look for playbooks
    :param identifier_prefix: internal var prefix
    :param include: list of files to
    :return: dict {"playbook_name_without_extension": "vars"}
    """

    res = {}
    for role_filename, contents in parse_path(path, include):
        role_name, role_vars = None, None
        for item in contents:
            if "hosts" not in item and "vars" not in item:
                continue
            role_name = item.get("hosts") or item["vars"].get(
                f"{identifier_prefix}_role"
            )
            if role_name is None:
                continue
            role_vars = item.get("vars", {})
        if role_name is None:
            raise AnsibleParserError(
                f"Failed to determine role name from  {role_filename}."
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


def get_inventory(path: Path, var_files: list, root_dir: str) -> dict:
    """
    Searches for var_files starting from path and stops at root_dir.

    :param path: starts searching up the tree from path
    :param var_files: list of files to search for
    :param root_dir: directory where to stop search
    :return: dict of var files merged in order, 0 being the least
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

    if var_files_copy:
        raise AnsibleParserError(f"failed to find: {var_files}, aborting")

    res = {}
    for var_filename in var_files:
        for variable_filepath in var_filepaths:
            if variable_filepath.name == var_filename:
                contents = data_loader.load_from_file(str(variable_filepath))
                if contents is None:
                    continue
                res.update(contents)
    return res


def get_role_defaults(path, identifier_prefix, playbook_vars):
    """
    Parses roles/$role/defaults/main.yml, if base_role is defined in
    playbook_vars parses roles/$base_role/defaults/main.yml

    :param path: base path containing roles
    :param identifier_prefix: internal var prefix
    :param playbook_vars: dict of playbook_vars
    :return: dict {"role_filename_without_extension": "vars"}
    """

    res = {}
    prefix_base_role = f"{identifier_prefix}_base_role"
    for role_name, role_vars in playbook_vars.items():
        defaults = path / role_name / "defaults" / "main.yml"
        if prefix_base_role in role_vars:
            defaults = path / role_vars[prefix_base_role] / "defaults" / "main.yml"
        try:
            res[role_name] = data_loader.load_from_file(str(defaults))
        except AnsibleFileNotFound:
            pass
    return res


def role_inventory_override(role_vars, identifier_prefix):
    """
    :param role_vars: dict of role variables
    :param identifier_prefix: internal var prefix
    :return: updated role_vars if any are overridden in $identifier_prefix_inventory_override
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
    :param jinja_env: jinja environment with ansible filters
    :param role_vars: role_vars which will be used to template jinja strings
    :return: templated role_vars
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
        ):
            pass

    return role_vars


def construct_hosts(role_vars: dict, jinja_env: jinja2.Environment) -> dict:
    """
    Constructs hosts from role_vars["hosts"] if found.

    :param role_vars: role_vars
    :param jinja_env: jinja environments, used to template variables in hosts keys
    :return: dict {"host": "hostvars"}
    """
    hosts = role_vars.get("hosts") or {}
    if not hosts:
        return {}

    res = {}
    templated_vars = template_vars(jinja_env, role_vars)
    for host, host_vars in hosts.items():
        hostname = host
        if is_possibly_template(host, jinja_env):
            hostname = jinja_env.from_string(host).render(**templated_vars)
        ranged_hostnames = [hostname]
        if detect_range(hostname):
            ranged_hostnames = expand_hostname_range(hostname)
        for item in ranged_hostnames:
            res[item] = {}
            if host_vars is not None and isinstance(host_vars, dict):
                res[item] = host_vars

    return res


def get_vars(path: Path, directories: list, inventory_vars: dict) -> dict:
    """
    Looks for var files in ansible-root/vars/$identifier_prefix_$dir_name/$var_value_defined
    in inventory.

    :param path: path to vars directory
    :param directories: list of directories to search for
    :param inventory_vars: dict of existing inventory variables

    :return: dict {"var_name": "var_value"}
    """
    res = {}
    for dir_name in directories:
        if dir_name not in inventory_vars:
            continue
        var_file = inventory_vars[dir_name]
        if not isinstance(var_file, str):
            continue
        for file in path.joinpath(dir_name).glob(f"{var_file}.y*"):
            if file.suffix not in [".yml", ".yaml"]:
                continue
            contents = data_loader.load_from_file(str(file))
            res |= contents or {}
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
        inventory_vars = get_inventory(
            inventory_path, self.get_option("inventory_var_files"), root_path.stem
        )
        group_vars = dict(parse_path(inventory_path))

        roles = []
        if self.get_option("role_source") == "inventory":
            roles = list(group_vars.keys())

        playbook_vars = get_playbook(root_path / "playbooks", identifier_prefix, roles)
        if self.get_option("role_source") == "playbooks":
            roles = list(playbook_vars.keys())

        role_defaults = get_role_defaults(
            root_path / "roles", identifier_prefix, playbook_vars
        )

        _vars = get_vars(
            root_path / "vars", self.get_option("var_dirs"), inventory_vars
        )

        for role in roles:
            self.inventory.add_group(role)

            role_vars = role_defaults.get(role, {})
            role_vars |= _vars
            role_vars |= inventory_vars
            role_vars |= role_inventory_override(role_vars, identifier_prefix)
            role_vars |= group_vars.get(role, {})
            role_vars |= playbook_vars.get(role, {})
            for k, v in role_vars.items():
                if k in ["hosts", f"{identifier_prefix}_inventory_override"]:
                    continue
                self.inventory.set_variable(role, k, v)

            hosts = construct_hosts(role_vars, jinja_env)
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
