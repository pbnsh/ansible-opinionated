from __future__ import absolute_import, division, print_function

__metaclass__ = type

import unittest
import tempfile
import shutil

from pathlib import Path

import yaml
import jinja2

from ansible.errors import AnsibleParserError
from ansible.plugins.filter.core import FilterModule

try:
    from ansible_collections.pbn.op.plugins.inventory.inventory import (
        get_root_path,
        parse_path,
        get_playbook,
        get_inventory,
        get_role_defaults,
        construct_hosts,
        template_vars,
        role_inventory_override,
        get_vars,
    )
except ImportError:
    import sys

    sys.path.append("plugins/inventory")
    sys.path.append("tests")
    # noinspection PyUnresolvedReferences
    from inventory import (
        get_root_path,
        parse_path,
        get_playbook,
        get_inventory,
        get_role_defaults,
        construct_hosts,
        template_vars,
        role_inventory_override,
        get_vars,
    )


class TestOpInventory(unittest.TestCase):
    test_dir = None
    jinja_env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    for k, v in FilterModule().filters().items():
        jinja_env.filters.update({k: v})

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_get_root_path_exists(self):
        p = self.test_dir / "foo" / "bar" / "baz"
        p.mkdir(parents=True)
        self.assertEqual(get_root_path(p, "foo"), self.test_dir / "foo")

    def test_ansible_root_path_raises(self):
        p = self.test_dir / "foo" / "bar" / "baz"
        p.mkdir(parents=True)
        with self.assertRaises(AnsibleParserError):
            get_root_path(p, "quux")

    def test_path_parse_include(self):
        p = self.test_dir / "test"
        p.mkdir(parents=True)
        for item in ["foo.yml", "bar.yaml", "quux", "quux.yml"]:
            p.joinpath(item).write_text(yaml.dump({"filename": item}))
        self.assertEqual(
            dict(parse_path(p, ["foo", "bar"])),
            {"foo": {"filename": "foo.yml"}, "bar": {"filename": "bar.yaml"}},
        )

    def test_get_inventory_merge_order(self):
        inventory_path = self.test_dir / "inventory" / "site" / "env"
        inventory_path.mkdir(parents=True)

        _common_p = self.test_dir / "inventory" / "_common.yml"
        _site_p = self.test_dir / "inventory" / "site" / "_site.yml"
        _env_p = self.test_dir / "inventory" / "site" / "env" / "_env.yml"

        _common_p.write_text(
            yaml.dump(
                {
                    "common_var": "initial",
                }
            )
        )
        _site_p.write_text(
            yaml.dump(
                {"test_site": "site", "common_var": "override", "site_var": "initial"}
            )
        )
        _env_p.write_text(
            yaml.dump({"test_env": "env", "site_var": "override", "env_var": "initial"})
        )
        inventory_vars = get_inventory(
            inventory_path, ["_common.yml", "_site.yml", "_env.yml"], self.test_dir
        )
        self.assertEqual(
            inventory_vars,
            {
                "common_var": "override",
                "env_var": "initial",
                "site_var": "override",
                "test_env": "env",
                "test_site": "site",
            },
        )

    def test_get_inventory_raises_on_missing(self):
        inventory_path = self.test_dir / "inventory" / "site" / "env"
        inventory_path.mkdir(parents=True)

        _common_p = self.test_dir / "inventory" / "_common.yml"
        _env_p = self.test_dir / "inventory" / "site" / "env" / "_env.yml"

        _common_p.write_text(
            yaml.dump(
                {
                    "common_var": "initial",
                }
            )
        )
        _env_p.write_text(
            yaml.dump({"test_site": "site", "test_env": "env", "env_var": "initial"})
        )

        with self.assertRaises(AnsibleParserError):
            get_inventory(
                inventory_path, ["_common.yml", "_site.yml", "_env.yml"], self.test_dir
            )

    def test_role_defaults_base_role(self):
        base_role_p = self.test_dir / "roles" / "base_role" / "defaults"
        base_role_p.mkdir(parents=True)
        base_role_p.joinpath("main.yml").write_text(
            yaml.dump({"base_role_var": "initial"})
        )

        playbook_vars = {"test": {"test_role": "test", "base_role": "base_role"}}

        role_defaults = get_role_defaults(
            self.test_dir / "roles", playbook_vars
        )
        self.assertEqual(role_defaults, {"test": {"base_role_var": "initial"}})

    def test_get_playbook(self):
        p = self.test_dir / "test"
        p.mkdir(parents=True)
        p.joinpath("playbook_one.yml").write_text(
            yaml.dump(
                [
                    {
                        "import_playbook": "_provision.yml",
                        "vars": {
                            "test_product": "test-product",
                            "test_role": "playbook_one",
                            "base_role": "test_role",
                        },
                    }
                ]
            )
        )
        p.joinpath("playbook_two.yml").write_text(
            yaml.dump(
                [
                    {
                        "import_playbook": "_provision.yml",
                        "vars": {
                            "test_product": "test-product",
                            "test_role": "playbook_two",
                        },
                    }
                ]
            )
        )

        self.assertEqual(
            get_playbook(p, "test", ["playbook_one"]),
            {
                "playbook_one": {
                    "base_role": "test_role",
                    "test_product": "test-product",
                    "test_role": "playbook_one",
                }
            },
        )

    def test_get_playbook_role_filename_mismatch_raises(self):
        p = self.test_dir / "test"
        p.mkdir(parents=True)
        p.joinpath("playbook_one.yml").write_text(
            yaml.dump(
                [
                    {
                        "import_playbook": "_provision.yml",
                        "vars": {
                            "test_product": "test-product",
                            "test_role": "playbook_role_var_name_mismatch",
                        },
                    }
                ]
            )
        )

        with self.assertRaises(AnsibleParserError):
            get_playbook(p, "test")

    def test_templated_vars(self):
        role_vars = {
            "test_site": "site",
            "test_env": "env",
            "test_dns_domain": "{{ test_site }}.{{ test_env }}.test",
            "ternary_filter_test": "{{ (true) | ternary('yes', 'no') }}",
        }
        templated_vars = template_vars(self.jinja_env, role_vars)
        self.assertEqual(
            templated_vars,
            {
                "ternary_filter_test": "yes",
                "test_dns_domain": "site.env.test",
                "test_env": "env",
                "test_site": "site",
            },
        )

    def test_construct_hosts(self):
        role_vars = {
            "hosts": {
                "test-host01": {"host01_var": "host01_value"},
                "test-host[02:03]": {"host_ranged_var": "host_ranged_value"},
                "test-host04.{{ test_site }}": {},
            },
            "role_var": "should_not_be_returned_by_construct_hosts",
            "test_site": "site",
        }

        self.assertEqual(
            construct_hosts(role_vars, self.jinja_env),
            {
                "test-host01": {"host01_var": "host01_value"},
                "test-host02": {"host_ranged_var": "host_ranged_value"},
                "test-host03": {"host_ranged_var": "host_ranged_value"},
                "test-host04.site": {},
            },
        )

    def test_role_inventory_override(self):
        role_vars = {
            "test_site": "site-name",
            "test_env": "env-name",
            "test_site_env": "site-name_env-name",
            "test_inventory_override": {
                "test_common": {
                    "default_variable_one": "overriden_in_role_defaults_common"
                },
                "test_env": {
                    "env-name": {
                        "default_variable_two": "overriden_in_role_defaults_env"
                    }
                },
                "test_site": {
                    "site-name": {
                        "default_variable_three": "overriden_in_role_defaults_site"
                    }
                },
                "test_site_env": {
                    "site-name_env-name": {
                        "default_variable_three": "overriden_in_role_defaults_site_env"
                    }
                },
            },
            "default_variable_one": "defaults",
            "default_variable_two": "defaults",
            "default_variable_three": "defaults",
        }
        role_vars |= role_inventory_override(role_vars, "test")
        del role_vars["test_inventory_override"]
        self.assertEqual(
            role_vars,
            {
                "test_site": "site-name",
                "test_env": "env-name",
                "test_site_env": "site-name_env-name",
                "default_variable_one": "overriden_in_role_defaults_common",
                "default_variable_two": "overriden_in_role_defaults_env",
                "default_variable_three": "overriden_in_role_defaults_site_env",
            },
        )

    def test_get_vars(self):
        test_provider_dir = self.test_dir / "vars" / "test_provider"
        test_env_dir = self.test_dir / "vars" / "test_env"

        for item in [test_provider_dir, test_env_dir]:
            item.mkdir(parents=True)

        test_provider_dir.joinpath("aws.yml").write_text(
            yaml.dump(
                {
                    "variable_one": "aws",
                }
            )
        )
        test_provider_dir.joinpath("proxmox.yaml").write_text(
            yaml.dump({"variable_one": "proxmox", "variable_two": "proxmox"})
        )
        test_env_dir.joinpath("dev.yml").write_text(
            yaml.dump({"variable_two": "dev", "variable_three": "dev"})
        )
        test_env_dir.joinpath("prod.yml").write_text(
            yaml.dump({"variable_one": "prod", "variable_three": "prod"})
        )

        vars_dirs = ["test_provider", "test_env"]
        inventory_vars = {"test_provider": "proxmox", "test_env": "prod"}

        p = self.test_dir / "vars"
        from pprint import pprint

        pprint(get_vars(p, vars_dirs))
        self.assertEqual(
            get_vars(p, vars_dirs),
            {
                "test_env": {
                    "dev": {"variable_three": "dev", "variable_two": "dev"},
                    "prod": {"variable_one": "prod", "variable_three": "prod"},
                },
                "test_provider": {
                    "aws": {"variable_one": "aws"},
                    "proxmox": {"variable_one": "proxmox", "variable_two": "proxmox"},
                },
            },
        )
