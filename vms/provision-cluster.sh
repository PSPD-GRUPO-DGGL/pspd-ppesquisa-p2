#!/bin/bash
# Script de automação IaC para provisionamento do cluster real via Multipass

set -e

echo "=== 1. Provisionando Máquinas Virtuais no Hypervisor ==="
multipass launch --name k8s-master --cpus 2 --memory 2G --disk 10G jammy
multipass launch --name k8s-worker1 --cpus 1 --memory 1.5G --disk 10G jammy
multipass launch --name k8s-worker2 --cpus 1 --memory 1.5G --disk 10G jammy
multipass launch --name k8s-worker3 --cpus 1 --memory 1.5G --disk 10G jammy

nodes=("k8s-master" "k8s-worker1" "k8s-worker2" "k8s-worker3")

for node in "${nodes[@]}"; do
  echo "=== 2. Configurando Core-Networking em $node ==="
  multipass exec "$node" -- sudo sh -c "
    # Desativar swap exigido pelo kubeadm
    swapoff -a
    sed -i '/swap/s/^/#/' /etc/fstab

    # Carregar os modulos do Kernel para Bridges do Kubeadm
    cat <<EOF > /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
    modprobe overlay
    modprobe br_netfilter

    # Aplicar sysctls de encaminhamento de pacotes exigidos pelo CNI
    cat <<EOF > /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
    sysctl --system

    # Instalar Containerd (Runtime de Container moderno)
    apt-get update && apt-get install -y containerd
    mkdir -p /etc/containerd
    containerd config default > /etc/containerd/config.toml
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /etc/containerd/config.toml
    systemctl restart containerd

    # Instalar Kubeadm, Kubelet e Kubectl
    apt-get update && apt-get install -y apt-transport-https ca-certificates curl
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' > /etc/apt/sources.list.d/kubernetes.list
    apt-get update
    apt-get install -y kubelet kubeadm kubectl
    apt-mark hold kubelet kubeadm kubectl
  "
done

echo "=== 3. Cluster provisionado e pronto para inicializacao! ==="
echo "Para inicializar, execute: multipass exec k8s-master -- sudo kubeadm init --pod-network-cidr=10.244.0.0/16"