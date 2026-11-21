#cloud-config
users:
  - name: user
    password: password
    lock_passwd: false
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - __SSH_PUBKEY__
ssh_pwauth: true
package_update: false
packages:
  - openssh-server
