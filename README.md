# Opinionated collections for Ansible.

## Included content

### Inventory plugins

| Name                                                                                           | Description     |
|------------------------------------------------------------------------------------------------|-----------------|
| [pbn.op.inventory](https://github.com/pbnsh/ansible-opinionated/tree/master/docs/inventory.md) | Flat inventory. |


## Installation

From archive:

```
VERSION=0.0.3
ansible-galaxy collection install "git+https://github.com/pbnsh/ansible-opinionated.git,v${VERSION}"
```

Via `requirements.yml` file:

```
VERSION=0.0.3
tee requirements.yml <<EOF > /dev/null
collections:
  - name: https://github.com/pbnsh/ansible-opinionated.git
    type: git
    version: "v${VERSION}"
EOF

ansible-galaxy install -r requirements.yml
```

### Usage

See [docs](https://github.com/pbnsh/ansible-opinionated/tree/master/docs) and [examples](https://github.com/pbnsh/ansible-opinionated/tree/master/examples) directories.

### Contributing

Via [go-task](https://github.com/go-task/task):

```
task sanity
task units
```

Manually:

```
TEST_DIR=/tmp/test-pbn-op

mkdir "${TEST_DIR}" || true
ansible-galaxy collection install {{.PWD}} -p {{.TEST_DIR}} --force
pushd .
cp -r tests "${TEST_DIR}/ansible_collections/pbn/op/"
cd "${TEST_DIR}/ansible_collections/pbn/op/"
ansible-test sanity --docker
ansible-test units --docker -v
popd
rm -r "${TEST_DIR}"
```
