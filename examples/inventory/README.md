# inventory


## role_source

The `role_source` option is set to `playbooks` in `sites/eu-central-1/dev/_inventory.yml`.

Inventory will return two hosts, test it:
```
ansible-playbook -i sites/eu-central-1/dev playbooks/webserver.yml --list-hosts
```

Running `playbooks/webserver.yml` as shown below, will return 0 hosts because
inventory is missing `webserver.yml` definition in site and `sites/equinix-he3/prod`
is configured with role_source = inventory (default).
```
ansible-playbook -i sites/equinix-he3/prod playbooks/webserver.yml --list-hosts
```
 
Create `webserver.yml` in `sites/equinix-he3/prod`, re-run ansible-playbook:
```
touch sites/equinix-he3/prod/webserver.yml
ansible-playbook -i sites/equinix-he3/prod playbooks/webserver.yml --list-hosts
```

Now hosts are picked up from `roles/webserver/defaults/main.yml`, hosts can also
be specified on site/env level by adding `hosts` to `sites/equinix-he3/prod/webserver.yml`.

## var_dirs

The `var_dirs` is configured as: `['pbn_provider', 'pbn_env']` with override
for `aws` provider and `dev` environment.

`sites/_common.yml` defines: `dns_servers`, `ntp_servers`, `host_cert_ttl` 
which are inherited by all site/env/roles.

Run the following to check how variables change depending on provider/env:
```
ansible-playbook -i sites/eu-central-1/dev playbooks/webserver.yml
ansible-playbook -i sites/eu-central-1/prod playbooks/webserver.yml
ansible-playbook -i sites/equinix-he3/prod playbooks/webserver.yml
```
