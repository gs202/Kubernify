# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| Latest  | :white_check_mark: |
| < Latest | :x:               |

Only the latest minor release receives security updates. Users are encouraged to upgrade promptly.

---

## Reporting a Vulnerability

If you discover a security vulnerability in kubernify, please report it responsibly.

### Preferred: GitHub Security Advisories

1. Go to the [Security Advisories](https://github.com/gs202/Kubernify/security/advisories) page
2. Click **"Report a vulnerability"**
3. Provide a detailed description of the issue, including steps to reproduce

### Alternative: Email

Send an email to the maintainers at the address listed in the repository's security advisory settings. Include:

- A description of the vulnerability
- Steps to reproduce
- Potential impact assessment
- Any suggested fixes (optional)

### What to Expect

- **Acknowledgment** within **48 hours** of your report
- **Initial assessment** within **7 days**
- **Fix or mitigation** within **90 days** of confirmed vulnerabilities
- Credit in the release notes (unless you prefer to remain anonymous)

**Please do not open public GitHub issues for security vulnerabilities.**

---

## Threat Model

### Read-Only by Design

kubernify is a **read-only verification tool**. It:

- **Only reads** cluster state via the Kubernetes API (`get`, `list` operations)
- **Never creates, updates, or deletes** any Kubernetes resources
- **Never modifies** cluster configuration
- **Never writes** to the Kubernetes API server

The RBAC permissions required are strictly read-only (see [README.md](README.md#rbac-permissions)).

### Credential Handling

kubernify **does not manage credentials directly**. Authentication is handled entirely by:

- **kubeconfig** — Standard `~/.kube/config` file managed by `kubectl` or cloud provider CLIs
- **In-cluster service accounts** — Kubernetes-native service account tokens mounted into pods
- **GKE auth plugin** — Google Cloud SDK's `gke-gcloud-auth-plugin` binary (when using `--gke-project`)

kubernify never stores, transmits, or logs credentials. It delegates all authentication to the [official Kubernetes Python client](https://github.com/kubernetes-client/python), which handles kubeconfig parsing and token refresh.

### Data Handling

- kubernify reads workload metadata (deployment specs, pod status, container images) from the Kubernetes API
- Output is written to stdout as structured JSON reports
- No data is sent to external services
- No telemetry or analytics are collected

---

## Security Considerations for Users

1. **Restrict RBAC permissions** — Grant kubernify's service account only the minimum required read permissions in the target namespace
2. **Use dedicated service accounts** — Avoid running kubernify with cluster-admin credentials
3. **Secure CI/CD secrets** — When using kubernify in pipelines, store kubeconfig and context names as encrypted secrets
4. **Review JSON output** — The structured report may contain workload names and image tags; treat pipeline logs accordingly

---

## Disclosure Policy

We follow a **coordinated disclosure** process:

1. Reporter submits vulnerability via GitHub Security Advisory or email
2. Maintainers acknowledge and assess the report
3. A fix is developed and tested privately
4. A new release is published with the fix
5. The security advisory is published with full details
6. The reporter is credited (if desired)

**Disclosure timeline:** 90 days from confirmed vulnerability to public disclosure. If a fix requires more time, we will coordinate with the reporter on an extended timeline.
