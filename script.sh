lxd init
# Would you like to use LXD clustering? (yes/no) [default=no]: yes
# What IP address or DNS name should be used to reach this server? [default=192.168.1.4]: 
# Are you joining an existing cluster? (yes/no) [default=no]: 
# What member name should be used to identify this server in the cluster? [default=arch-agregat]: 
# Do you want to configure a new local storage pool? (yes/no) [default=yes]: 
# Do you want to configure a new remote storage pool? (yes/no) [default=no]: 
# Would you like to configure LXD to use an existing bridge or host interface? (yes/no) [default=no]: 
# Would you like stale cached images to be updated automatically? (yes/no) [default=yes]: 
# Would you like a YAML "lxd init" preseed to be printed? (yes/no) [default=no]: 

lxc launch images:debian/12 test
lxc list

ip link
lxc network create lxdbr0 ipv4.address=auto ipv6.address=auto
lxc network attach-profile lxdbr0 default eth0


lxc launch images:debian/12 vm1 --vm
lxc launch images:debian/12 vm2 --vm
lxc launch images:debian/12 vm3 --vm

lxc stop vm1
lxc stop vm2
lxc stop vm3

lxc config set vm1 limits.cpu 2
lxc config set vm1 limits.memory 2GB
lxc config set vm2 limits.cpu 2
lxc config set vm2 limits.memory 2GB
lxc config set vm3 limits.cpu 2
lxc config set vm3 limits.memory 2GB


lxc start vm1
lxc start vm2
lxc start vm3


lxc exec vm1 -- bash
    apt update && apt install -y snapd
    snap install lxd
    exit

lxc exec vm2 -- bash
    apt update && apt install -y snapd
    snap install lxd
    exit

lxc exec vm3 -- bash
    apt update && apt install -y snapd
    snap install lxd
    exit



lxc exec vm1 -- bash
    lxd init
    # root@vm1:~# lxd init
    # Would you like to use LXD clustering? (yes/no) [default=no]: yes
    # What IP address or DNS name should be used to reach this server? [default=10.144.35.211]: 
    # Are you joining an existing cluster? (yes/no) [default=no]: 
    # What member name should be used to identify this server in the cluster? [default=vm1]: 
    # Do you want to configure a new local storage pool? (yes/no) [default=yes]: 
    # Name of the storage backend to use (btrfs, dir, lvm) [default=btrfs]: dir
    # Do you want to configure a new remote storage pool? (yes/no) [default=no]: 
    # Would you like to connect to a MAAS server? (yes/no) [default=no]: 
    # Would you like to configure LXD to use an existing bridge or host interface? (yes/no) [default=no]: 
    # Would you like stale cached images to be updated automatically? (yes/no) [default=yes]: 
    # Would you like a YAML "lxd init" preseed to be printed? (yes/no) [default=no]: 
    # root@vm1:~# 
    exit


lxc exec vm1 -- bash
    lxc cluster add vm2
    lxc cluster add vm3
    exit

lxc exec vm2 -- bash
    lxd init
    # Would you like to use LXD clustering? (yes/no) [default=no]: yes
    # What IP address or DNS name should be used to reach this server? [default=10.144.35.87]: 
    # Are you joining an existing cluster? (yes/no) [default=no]: yes
    # Do you have a join token? (yes/no/[token]) [default=no]: yes
    # Please provide join token: [TOKEN]
    # All existing data is lost when joining a cluster, continue? (yes/no) [default=no] yes
    # Choose "source" property for storage pool "local": 
    # Would you like a YAML "lxd init" preseed to be printed? (yes/no) [default=no]: 

lxc exec vm3 -- bash
    lxd init
    # Would you like to use LXD clustering? (yes/no) [default=no]: yes
    # What IP address or DNS name should be used to reach this server? [default=10.144.35.78]: 
    # Are you joining an existing cluster? (yes/no) [default=no]: yes
    # Do you have a join token? (yes/no/[token]) [default=no]: yes
    # Please provide join token: [TOKEN]
    # All existing data is lost when joining a cluster, continue? (yes/no) [default=no] yes
    # Choose "source" property for storage pool "local": 
    # Would you like a YAML "lxd init" preseed to be printed? (yes/no) [default=no]: 
    exit


sudo pacman -S nfs-utils
sudo mkdir -p /srv/lxd-shared
sudo nano /etc/exports

echo '/srv/lxd-shared *(rw,sync,no_subtree_check,no_root_squash)' >> /etc/exports

sudo systemctl enable --now nfs-server
sudo exportfs -arv

lxc exec vm1 -- bash -c "apt update && apt install -y nfs-common"
lxc exec vm2 -- bash -c "apt update && apt install -y nfs-common"
lxc exec vm3 -- bash -c "apt update && apt install -y nfs-common"

lxc exec vm1 -- bash -c "mkdir -p /mnt/lxd-shared && mount 10.144.35.1:/srv/lxd-shared /mnt/lxd-shared"
lxc exec vm2 -- bash -c "mkdir -p /mnt/lxd-shared && mount 10.144.35.1:/srv/lxd-shared /mnt/lxd-shared"
lxc exec vm3 -- bash -c "mkdir -p /mnt/lxd-shared && mount 10.144.35.1:/srv/lxd-shared /mnt/lxd-shared"


lxc exec vm1 -- bash -c "echo 'hello from vm1' > /mnt/lxd-shared/test.txt"

lxc exec vm2 -- bash -c "cat /mnt/lxd-shared/test.txt"
lxc exec vm3 -- bash -c "cat /mnt/lxd-shared/test.txt"


