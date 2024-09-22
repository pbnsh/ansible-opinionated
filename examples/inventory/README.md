# inventory

## var_dirs

The `var_dirs` is configured as: `['pbn_provider', 'pbn_env']` with override
for `aws` provider and `dev` environment.

`sites/_common.yml` defines: `dns_servers`, `ntp_servers`, `host_cert_ttl` 
which are used by all roles.

In dev environment, `host_cert_ttl` is overridden and 

Run the following to check how variables change depending on provider/env:
```
ansible-playbook -i sites/eu-central-1/dev playbooks/webserver.yml
ansible-playbook -i sites/eu-central-1/prod playbooks/webserver.yml
ansible-playbook -i sites/equinix-he3/prod playbooks/webserver.yml
```
