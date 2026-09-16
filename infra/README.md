# Infrastructure

Ansible playbooks and Kubernetes manifests for deploying the composer stack.
The cluster itself (kubeadm, Flannel, MetalLB) is managed by the
[eightbitsaxlounge/server](../../nineteenseventytwo-eightbitsaxlounge/server) layer.
This folder only adds what is specific to the composer/LLM workload.

## Node Layout

| Node | Hardware | Role | Workloads |
|---|---|---|---|
| 1972-console-1 (192.168.68.201) | RPi — CI/CD | kubeadm control plane, GitHub Actions | Ansible, runs playbooks |
| 1972-master-1 (192.168.68.202) | RPi5 | Kubernetes master | API server |
| 1972-worker-1/2 (203/204) | RPi4 | Kubernetes workers | General workloads |
| 1972-home (192.168.68.205) | PC — Linux boot | Kubernetes GPU worker | **llm-server, training** |
| midi-host (192.168.68.205) | PC — Windows boot | MIDI API host | Windows-only services |

**GPU node capacity:** 7B–8B models at Q4-Q8 run fully in VRAM (~5-6 GB of 8 GB). 13B models with partial CPU offload. Effective for agentic pipelines using Llama/Mistral 7-8B class.

## Structure

```
infra/
  ansible/
    playbooks/
      bootstrap-linux.sh   # Manual step: run once on fresh Ubuntu install
      setup-gpu-node.yaml  # Automated: NVIDIA drivers, kubeadm join, firewall
      deploy-services.yaml # Deploy composer K8s services
    inventory/
      hosts.yaml           # Reference/dev inventory (deployed inventory is on 1972-console-1)
  k8s/
    namespace.yaml         # Kubernetes namespace
    composer/              # Composer service K8s manifests
```

## Deployed Inventory

The live Ansible inventory on 1972-console-1 (`/etc/ansible/hosts`) is the source of truth.
It is generated from `eightbitsaxlounge/server/templates/ansiblehosts.j2` and includes
the `[gpu_nodes]` group. To re-deploy it after changes to `vars.yaml` or `ansiblehosts.j2`:

```bash
# On 1972-console-1
cd ~/nineteenseventytwo-eightbitsaxlounge/server
make init-console-config
```

## Adding the PC as a GPU Cluster Node

### 1 — Storage: Install a dedicated Linux drive

**Recommended: a second NVMe or SATA SSD dedicated to Linux.**  
This is simpler and safer than dual-partitioning the existing Windows NVMe.

- Check if your motherboard has a second M.2 slot (B550/X570 boards typically have 2).
  If yes, a second NVMe (500 GB – 1 TB) is the cleanest option.
  If no M.2 slot, a 500 GB SATA SSD works fine.
- Minimum useful size: **500 GB** — models (Ollama) are 4-8 GB each; `/var` grows fast.
- Partitioning suggestion (in the Ubuntu installer):
  - EFI — 512 MB (new, on the Linux drive — BIOS will show both; pick via boot menu)
  - `/` — 50 GB ext4
  - `/var` — 350 GB+ ext4 (container images + Ollama model cache)
  - `swap` — 16 GB (headroom for CPU-offloaded model layers)
  - `/home` — remainder
- Set boot order in BIOS: Linux drive first. Hold F8/F12 to choose Windows NVMe when needed.

### 2 — Networking: Use the GS308E Ethernet port

Connect the PC to the Netgear GS308E with an Ethernet cable.
You already have room on the switch. This is strongly preferred over Wi-Fi for a cluster node.

- The PC's Ethernet NIC has the same MAC address in both Windows and Linux boots,
  so one DHCP reservation in the Deco app covers both OS boots → same IP (192.168.68.50).
- Switch from the current Windows-side static IP assignment to a Deco DHCP reservation
  (the same way you set it up for the Pi nodes). That way Linux gets the same IP automatically.

### 3 — Install Ubuntu 24.04 LTS

Boot from a USB key. Install to the dedicated Linux drive with the partitioning above.
In the installer:
- Set hostname: `1972-gpu-1`
- Set username: `mchellmer` (matches the rest of the cluster)

### 4 — Bootstrap SSH (manual, ~2 minutes)

On 1972-console-1, the `pi-to-midi-host` key was already created by `init-pc.yaml`.
Pass its public key to the bootstrap script:

```bash
# On 1972-console-1 — get the public key
cat ~/.ssh/pi-to-midi-host.pub

# On the new Ubuntu node
sudo bash ~/nineteenseventytwo-composer/infra/ansible/playbooks/bootstrap-linux.sh \
  "<pi-to-midi-host.pub contents>"
```

The script creates the `mchellmer` user, configures the SSH key, and opens UFW ports.

### 5 — Re-deploy the Ansible inventory

If you have not already updated `ansiblehosts.j2` and `vars.yaml` in the eightbitsaxlounge repo,
do that first (they already include the `[gpu_nodes]` group). Then on 1972-console-1:

```bash
cd ~/nineteenseventytwo-eightbitsaxlounge/server
make init-console-config
```

### 6 — Verify connectivity

```bash
# On 1972-console-1
ansible gpu_nodes -m ping
```

### 7 — Run the GPU node setup playbook

From 1972-console-1:

```bash
cd ~/nineteenseventytwo-eightbitsaxlounge/server
make init-gpu
```

Or directly:

```bash
ansible-playbook ~/nineteenseventytwo-composer/infra/ansible/playbooks/setup-gpu-node.yaml -K
```

The playbook covers:
- Ubuntu package update (mirrors `init-nodes.yaml` pattern)
- Kubernetes 1.35 packages (matching the existing cluster)
- NVIDIA driver install (`ubuntu-drivers autoinstall`, reboot if needed)
- NVIDIA Container Toolkit + containerd runtime config
- iptables bridge settings (same as `k8s_iptables` role on Pi workers)
- Fetches the kubeadm join command from the master and joins the cluster
- NVIDIA device plugin DaemonSet deployed
- UFW firewall rules
- Node labelled `workload=llm, gpu=true` for scheduler targeting

### 8 — Verify the node joined

```bash
kubectl get nodes -o wide
kubectl describe node 1972-gpu-1 | grep -A5 "Capacity"
# Should show: nvidia.com/gpu: 1
```

---

## Deploying Composer Services

```bash
ansible-playbook ~/nineteenseventytwo-composer/infra/ansible/playbooks/deploy-services.yaml
```

The `llm-server` deployment targets the GPU node via `nodeSelector: workload: llm`.


