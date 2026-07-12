export interface BuildCiliumNetworkPolicyInput {
  namespace: string;
  fabricServerNamespace: string;
  egressAllowFqdns: string[];
  egressAllowCidrs: string[];
}

// Design note: no ingress rules are defined here. HermesFabric-server does NOT
// push to agent pods — agents make outbound (egress) callbacks to
// fabric-server on port 3100. If server→agent push is ever needed, add a
// targeted ingress rule scoped to the fabric-server endpoint selector.
export function buildCiliumNetworkPolicyManifest(input: BuildCiliumNetworkPolicyInput): Record<string, unknown> {
  const egress: Record<string, unknown>[] = [];

  egress.push({
    toEndpoints: [
      { matchLabels: { "k8s:io.kubernetes.pod.namespace": "kube-system", "k8s-app": "kube-dns" } },
    ],
    toPorts: [
      {
        ports: [
          { port: "53", protocol: "UDP" },
          { port: "53", protocol: "TCP" },
        ],
        rules: { dns: [{ matchPattern: "*" }] },
      },
    ],
  });

  if (input.egressAllowFqdns.length > 0) {
    egress.push({
      toFQDNs: input.egressAllowFqdns.map((fqdn) => ({ matchName: fqdn })),
      toPorts: [{ ports: [{ port: "443", protocol: "TCP" }] }],
    });
  }

  egress.push({
    toEndpoints: [
      {
        matchLabels: {
          "k8s:io.kubernetes.pod.namespace": input.fabricServerNamespace,
          app: "fabric-server",
        },
      },
    ],
    toPorts: [{ ports: [{ port: "3100", protocol: "TCP" }] }],
  });

  if (input.egressAllowCidrs.length > 0) {
    egress.push({
      toCIDRSet: input.egressAllowCidrs.map((cidr) => ({ cidr })),
    });
  }

  return {
    apiVersion: "cilium.io/v2",
    kind: "CiliumNetworkPolicy",
    metadata: {
      name: "fabric-egress-fqdn",
      namespace: input.namespace,
      labels: { "fabric.io/managed-by": "fabric-k8s-plugin" },
    },
    spec: {
      endpointSelector: { matchLabels: { "fabric.io/role": "agent" } },
      egress,
    },
  };
}
