# Relatório de Pesquisa: Observabilidade e Monitoramento em Clusters K8S

## 1. Experiência de Montagem do Kubernetes em Cluster

### 1.1 Cluster de Alta Fidelidade Local (Kind)
O Kind foi estruturado em arquitetura multi-node contendo 1 nó de Control Plane e 3 nós Workers. A mapeamento de portas do barramento de host foi configurado por meio da diretiva `extraPortMappings` conectada à porta local `30080` de modo que a ferramenta k6 possa se manter no host local e não roubar ciclos de processamento computacional dos containers do cluster durante as simulações, evitando contaminação de latências percentílicas.

### 1.2 Cluster de VMs de Produção Físico (Multipass / Kubeadm)
Para a validação estrutural em instâncias virtuais nativas de produção de acordo com as ementas da disciplina, desenvolveu-se o runbook IaC em `vms/provision-cluster.sh` automatizando:
- Alocação do hypervisor em jammy images.
- Ajuste dos parâmetros do subsistema de rede do Linux Kernel: `net.bridge.bridge-nf-call-iptables`.
- Setup do runtime `containerd` configurando o Systemd de forma a tratar os cgroups unificados.

## 2. Metodologia de Coleta e Fases do Projeto

### 2.1 Fase (b): Testes de Desempenho e Coleta de Métricas
[Preencher com as tabelas comparativas das corridas k6 após integração]

### 2.2 Fase (c) / (d): Resiliência e Autoscaling Dinâmico por CPU e Métricas Customizadas
O comportamento do Horizontal Pod Autoscaler (HPA) foi testado sob duas abordagens complementares:
1. **HPA por CPU:** Escalonamento horizontal acionado ao atingir média de concorrência computacional de target especificado em \( 60\% \).
2. **HPA por Métricas Customizadas (Request Rate):** Configuração de escalonamento baseado em requisições através do `prometheus-adapter` e endpoints do APIService, mapeado em `k8s/app/hpa-custom-metric.yaml`.

...