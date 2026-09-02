# Infrastructure: How a Request Reaches Your Code

> **Sanitised copy.** Real project IDs, IPs, domains, and service-account names
> are replaced with `<PLACEHOLDERS>`. The operator's full-detail counterpart is
> `.agent/infrastructure_local.md` (gitignored). **Edit both together** — see
> [AGENTS.md](../AGENTS.md#paired-documentation).

This explains how the pieces of this project fit together — the application
services, Terraform, GCP, and the networking that connects a browser to a
container. `docs/architecture.md` covers what happens *inside* the app; this
covers everything *before* that.

It is written for someone who has not worked with DNS, load balancers, or
Terraform before, and uses this project's real resource names throughout.

---

## 1. The one-paragraph version

You own the domain `<APEX_DOMAIN>`. Someone types it into a browser. DNS
translates that name into an IP address — `<LB_IPV4>` — which belongs to a
Google load balancer. The load balancer terminates HTTPS, looks at *which*
hostname was requested (`api.` vs `app.` vs `games.`), and forwards the request
to one of three Cloud Run services, each a container running your code.
Terraform is the tool that created every piece of that except the containers
themselves.

```text
Browser                                                        Your code
   |                                                                ^
   | 1. "what IP is api.<APEX_DOMAIN>?"                           |
   v                                                                |
  DNS  ---> <LB_IPV4>                                          |
   |                                                                |
   | 2. HTTPS request to that IP, saying "Host: api.<APEX_DOMAIN>"|
   v                                                                |
Global Load Balancer                                                |
   |  - proves identity with an SSL certificate                     |
   |  - reads the Host header, picks a backend                      |
   v                                                                |
Serverless NEG  --->  Cloud Run service (api-core)  ----------------+
```

---

## 2. DNS: turning names into numbers

Computers route by IP address (`<LB_IPV4>`). Humans use names
(`api.<APEX_DOMAIN>`). DNS is the global lookup system that maps one to the
other. Understanding it requires separating four things people usually blur
together.

### The registrar vs. the DNS host

These are **different jobs**, often sold by the same company, which is the root
of most confusion.

| Role          | What it does                                                                                         | Who does it here |
| ------------- | ---------------------------------------------------------------------------------------------------- | ---------------- |
| **Registrar** | Owns your *registration* of the name. Bills you yearly. Records which nameservers are authoritative. | <registrar>      |
| **DNS host**  | Actually answers the lookup questions — "what IP is `api.<APEX_DOMAIN>`?"                          | Google Cloud DNS |

<registrar> *can* host DNS too (it did, by default). We moved that job to Cloud
DNS so Terraform can manage records as code. The registrar still owns the
registration — we only changed who answers the questions.

### Nameservers (NS): the pointer

A **nameserver** is a server that answers DNS questions for a domain. At the
registrar you set which nameservers are authoritative for your domain. That is
the *only* DNS setting the registrar really controls once you delegate.

This project's zone uses:

```text
ns-cloud-a1.googledomains.com
ns-cloud-a2.googledomains.com
ns-cloud-a3.googledomains.com
ns-cloud-a4.googledomains.com
```

Setting those at <registrar> is called **delegation**: "I am handing DNS
responsibility for this domain to Google Cloud DNS."

Before delegation, <registrar> answered lookups from its own record set — which
still held old Google Sites addresses (`<legacy parking IPs>`). The Terraform-managed
Cloud DNS zone had all the correct records, but *nobody was asking it*. This is
why the site was unreachable even though the infrastructure was perfect: the
records existed, but the world was querying the wrong server.

> **Lesson:** correct DNS records in an un-delegated zone do nothing. Delegation
> is what makes them real.

### Records: the actual answers

Inside the Cloud DNS zone, records hold the answers. This project uses `A`
records (name → IPv4):

```text
<APEX_DOMAIN>.        A  <LB_IPV4>
www.<APEX_DOMAIN>.    A  <LB_IPV4>
api.<APEX_DOMAIN>.    A  <LB_IPV4>
app.<APEX_DOMAIN>.    A  <LB_IPV4>
games.<APEX_DOMAIN>.  A  <LB_IPV4>
```

Note **all five point to the same IP**. There is one load balancer; it decides
what to do based on the hostname in the request, not the address. Terraform
creates these from `var.subdomains` in `modules/dns`.

Other record types you saw at the registrar:

- **AAAA** — same as A, but IPv6.
- **CNAME** — alias to another *name* rather than an IP (`www` → `ghs.googlehosted.com`).
- **TXT** — arbitrary text; commonly used to prove domain ownership.
- **NS** — delegation pointers (above).
- **DS** — DNSSEC trust anchor (below).

### TTL and propagation

Each record has a **TTL** (time-to-live) in seconds — how long resolvers may
cache the answer. <registrar>'s records used 4 hours; this project's use 300s
(5 minutes), so changes take effect quickly.

"Propagation takes 48 hours" is a worst-case caution. What actually happens: old
answers expire from caches at their own pace. In practice delegation here was
visible within minutes.

### What are 8.8.8.8 and 1.1.1.1?

**Public recursive resolvers** — free DNS servers anyone can query.

- `8.8.8.8` — Google Public DNS
- `1.1.1.1` — Cloudflare DNS

Normally your computer uses whatever resolver your ISP or router provides. When
verifying a DNS change, querying these directly is useful because they are
*independent of your local setup* — if `8.8.8.8` and `1.1.1.1` both return the
new answer, the change is genuinely live for the world, not just cached locally.

```bash
nslookup api.<APEX_DOMAIN> 8.8.8.8    # ask Google's resolver
nslookup -type=NS <APEX_DOMAIN> 1.1.1.1   # check delegation via Cloudflare
```

There is nothing special about these two beyond being memorable and public.

### DNSSEC and DS records

Plain DNS is unauthenticated — a malicious resolver can lie about an IP.
**DNSSEC** adds cryptographic signatures so resolvers can verify answers.

Two halves must agree:

1. **Signing** — the DNS host signs the zone. Cloud DNS does this; Terraform
   enables it in `modules/dns/main.tf` (`dnssec_config { state = "on" }`).
2. **The DS record** — published at the registrar, pointing up to the `.dev`
   registry. It says "here is the fingerprint of the key that signs my zone."

The DS record is the link in the chain of trust. This is why the registrar made
you disable DNSSEC before changing nameservers: the existing DS record pinned
*<registrar>'s* signing keys. Changing nameservers without removing it would
leave validating resolvers unable to verify the new zone — they would return
**SERVFAIL** and the domain would go dark everywhere.

> **Order matters:** disable DNSSEC → change nameservers → (later, optionally)
> publish a new DS record matching Cloud DNS's key. Publishing a wrong DS record
> breaks the domain completely, so it is done deliberately and last.

Get the current key with:

```bash
gcloud dns dns-keys list --zone=<DNS_ZONE> --project=<project>
```

---

## 3. HTTPS and SSL certificates

`.dev` is on the browser **HSTS preload list**, meaning browsers refuse plain
HTTP for it. HTTPS is mandatory, not optional.

An **SSL/TLS certificate** proves that the server answering for
`api.<APEX_DOMAIN>` is legitimately authorised for that name. Browsers trust
certificates issued by recognised authorities.

This project uses **Google-managed certificates** — Google obtains and renews
them automatically. Terraform declares one per hostname in `modules/edge_lb`:

```text
cv-edge-cert-<DNS_ZONE>        (apex)
cv-edge-cert-www-<DNS_ZONE>
cv-edge-cert-api-<DNS_ZONE>
cv-edge-cert-app-<DNS_ZONE>
cv-edge-cert-games-<DNS_ZONE>
```

### Why certificates depend on DNS

To issue a certificate, Google must confirm you control the domain. It does this
by resolving the hostname and checking it points at *your* load balancer.

**This creates a strict ordering:** DNS must work before certificates can issue.
While delegation was missing, every certificate sat in:

```text
managed.status:       PROVISIONING
managed.domainStatus: <APEX_DOMAIN>=FAILED_NOT_VISIBLE
```

`FAILED_NOT_VISIBLE` means exactly "the hostname does not resolve to this load
balancer." It is not a certificate bug — it is DNS reported one layer up. Once
DNS resolved correctly, the certificates provisioned on their own within
roughly 15–60 minutes.

```bash
gcloud compute ssl-certificates list --global --project=<project> \
  --format='table(name,managed.status,managed.domainStatus)'
```

---

## 4. The load balancer: one IP, many services

All five hostnames resolve to a single **Global External Application Load
Balancer**. It is assembled from several GCP resources, all in
`terraform/modules/edge_lb/main.tf`:

| Resource                                | Purpose                                          |
| --------------------------------------- | ------------------------------------------------ |
| `google_compute_global_address`         | The static public IP (`<LB_IPV4>`)          |
| `google_compute_global_forwarding_rule` | Binds that IP + port 443 to the proxy            |
| `google_compute_target_https_proxy`     | Terminates TLS using the certificates            |
| `google_compute_url_map`                | Routing rules: which hostname → which backend    |
| `google_compute_backend_service`        | Points at a serverless NEG (a Cloud Run service) |
| `google_compute_backend_bucket`         | Points at a GCS bucket (static assets/CDN)       |

### How routing works

The **URL map** is the decision-maker. For each hostname it defines a host rule
and a path matcher:

```text
Host: api.<APEX_DOMAIN>    -> backend service -> NEG -> api-core
Host: www.<APEX_DOMAIN>    -> backend service -> NEG -> api-core
Host: <APEX_DOMAIN>        -> backend service -> NEG -> api-core
Host: app.<APEX_DOMAIN>    -> backend service -> NEG -> spa-origin
      app.<APEX_DOMAIN>/assets/*  -> backend bucket (CDN, static files)
Host: games.<APEX_DOMAIN>  -> backend service -> NEG -> api-games
```

Three hostnames share one service (`api-core`) while `app.` splits by path —
`/assets/*` served from a CDN bucket, everything else from the container. This
is why `variables.tf` separates `services` (distinct workloads) from
`host_routing` (hostname → workload): the mapping is many-to-one.

### Serverless NEGs

A **Network Endpoint Group** is the adapter between the load balancer (which
speaks the Compute Engine world) and Cloud Run (which is serverless). Terraform
creates one per service in `modules/cloud_run_service`. You rarely interact with
them directly, but they appear in `terraform plan` output and require the
deployer to hold `compute.viewer` to read them.

### Ingress: why `*.run.app` URLs return 404

Each Cloud Run service sets:

```text
ingress: internal-and-cloud-load-balancing
```

This **rejects direct traffic** to the service's own
`https://api-core-....run.app` URL. Requests must arrive through the load
balancer. Hitting the `.run.app` URL directly returns 404 — that is the security
setting working, not a broken deployment. Always test through the real hostname.

---

## 5. Cloud Run: where the code runs

Three services, each a container:

| Service      | Contents                                       | Hostnames            |
| ------------ | ---------------------------------------------- | -------------------- |
| `api-core`   | FastAPI + FastMCP (`Dockerfile`)               | apex, `www.`, `api.` |
| `spa-origin` | React SPA behind nginx (`frontend/Dockerfile`) | `app.`               |
| `api-games`  | Games service (`services/games/Dockerfile`)    | `games.`             |

Cloud Run scales to zero when idle, so cost is near-nil at low traffic. Each
service runs as its own **service account** (`api-core-runtime@…` etc.), giving
each only the permissions it needs — `api-core` can read the CV bucket; the
others cannot.

Images live in **Artifact Registry**:

```text
europe-west1-docker.pkg.dev/<project>/cv-images/<service>:<git-sha>
```

Tagging by commit SHA makes every deployment traceable and rollback a matter of
redeploying an earlier tag.

---

## 6. Terraform: the infrastructure as code

Everything above — DNS zone, records, IP, certificates, load balancer, Cloud Run
services, IAM, Artifact Registry — is *declared* in `terraform/`. You describe
the desired end state; Terraform computes the difference against reality and
applies it.

### State

Terraform records what it created in a **state file**, stored in a GCS bucket
(`<project>-dev-tfstate`). This is why the bucket is created by a bootstrap
script rather than Terraform: Terraform cannot store its own state in a bucket
it has not created yet — the classic chicken-and-egg, solved with one manual
step.

The bucket has **object versioning** enabled, which serves double duty: history
for recovery, and the locking mechanism preventing two applies at once.

### Modules

Reusable groupings under `terraform/modules/`:

```text
gcp_apis/           enable GCP APIs
iam_secrets/        service accounts, IAM, Artifact Registry
github_wif/         keyless CI authentication
cloud_run_service/  one Cloud Run service + its NEG
edge_lb/            IP, certificates, URL map, proxy
dns/                DNS zone + records
static_bucket/      CDN origin bucket
```

### The ownership boundary

The key rule, and the reason CI/CD is split into two workflows:

> **Terraform owns the platform. The app pipeline owns the released artifact.**

Terraform defines a Cloud Run service's *shape* — memory, scaling, env vars,
secrets, ingress. But *which image tag is live* is owned by `gcloud run deploy`
in `deploy-app.yml`.

Without care these two would fight: Terraform would revert to the tag in its
config, undoing your latest deploy. The fix is in
`modules/cloud_run_service/main.tf`:

```hcl
lifecycle {
  ignore_changes = [template[0].containers[0].image]
}
```

"Manage everything about this service except the image tag." That single block
is what makes the split safe.

### Why the split matters

| Change   | Workflow         | Why                                                |
| -------- | ---------------- | -------------------------------------------------- |
| App code | `deploy-app.yml` | Fast, no state access, rollback = redeploy old tag |
| Infra    | `ci-cd.yml`      | Plan → review → gated apply                        |

Routing every code release through `terraform apply` would mean every deploy
touches IAM, DNS, and networking state — turning a routine rollout into a
full-infrastructure operation.

---

## 7. Identity: how CI talks to GCP without keys

CI needs GCP permissions, but storing a service account key in GitHub would mean
a long-lived credential that leaks badly.

Instead this project uses **Workload Identity Federation**: GitHub Actions
presents a short-lived OIDC token proving "I am a workflow in
`<GITHUB_OWNER>/<REPO>`", and GCP exchanges it for temporary
credentials for the `deployer@` service account. No stored keys.

Configured in `modules/github_wif`, with an attribute condition restricting
trust to this repository — otherwise any GitHub repo could request access.

> **A hard-won detail:** the `GCP_DEPLOY_SA` GitHub secret must name the service
> account Terraform manages (`deployer@…`). It once pointed at an older,
> unmanaged account with only partial permissions. Symptoms were baffling:
> `gcloud builds submit` worked, `gcloud run deploy` failed with an `actAs`
> denial, and granting more roles changed nothing — because the grants went to
> an account CI was not using. If IAM looks correct but is denied anyway,
> verify *which identity is authenticated* before granting anything further.

---

## 8. Putting it together: a request end to end

Someone opens `https://app.<APEX_DOMAIN>`:

1. **DNS** — browser asks a resolver; the query reaches Cloud DNS via the
   delegated nameservers, returning `<LB_IPV4>` (cached 300s).
2. **TCP + TLS** — browser connects on port 443. The forwarding rule sends it to
   the HTTPS proxy, which presents `cv-edge-cert-app-<DNS_ZONE>`. The
   browser verifies it and the connection encrypts.
3. **Routing** — the proxy passes the decrypted request to the URL map, which
   reads `Host: app.<APEX_DOMAIN>`. A `/assets/*` path goes to the CDN bucket;
   anything else goes to the `spa-origin` backend service.
4. **Backend** — the backend service forwards to the serverless NEG, which
   delivers to the Cloud Run service (cold-starting a container if scaled to
   zero).
5. **Application** — nginx serves the React app. `docs/architecture.md` takes
   over from here.

---

## 9. Debugging by layer

Faults are easiest to find by testing each layer independently, outermost first.

```bash
# 1. Delegation — are the right nameservers authoritative?
nslookup -type=NS <APEX_DOMAIN> 8.8.8.8

# 2. Resolution — does the hostname return the LB IP?
nslookup api.<APEX_DOMAIN> 8.8.8.8

# 3. Certificates — provisioned, or blocked on DNS?
gcloud compute ssl-certificates list --global --project=<project> \
  --format='table(name,managed.status,managed.domainStatus)'

# 4. Routing — does the LB have the expected host rules?
gcloud compute url-maps describe cv-edge-url-map --project=<project>

# 5. Service — which image is live?
gcloud run services describe api-core --region=europe-west1 --project=<project> \
  --format='value(spec.template.spec.containers[0].image)'

# 6. Application logs
gcloud run services logs read api-core --region=europe-west1 --project=<project>
```

Common symptoms:

| Symptom                          | Likely cause                                                                     |
| -------------------------------- | -------------------------------------------------------------------------------- |
| Hostname does not resolve        | Delegation missing, or record absent from the zone                               |
| Resolves to an unexpected IP     | Registrar still hosting DNS; or a stale cached TTL                               |
| Certificate `FAILED_NOT_VISIBLE` | DNS does not point at the load balancer                                          |
| `SERVFAIL` everywhere            | DNSSEC mismatch — DS record disagrees with the signing key                       |
| 404 on `*.run.app`               | Expected: `ingress` restricts to load-balancer traffic                           |
| 403 `actAs` in CI                | Deployer identity lacks `serviceAccountUser` — check *which* SA is authenticated |

---

## Glossary

| Term                    | Meaning                                                       |
| ----------------------- | ------------------------------------------------------------- |
| **A record**            | Maps a name to an IPv4 address                                |
| **AAAA record**         | Maps a name to an IPv6 address                                |
| **CNAME**               | Alias from one name to another name                           |
| **NS record**           | Names the authoritative servers for a domain                  |
| **DS record**           | DNSSEC fingerprint linking a zone to its parent's trust chain |
| **TXT record**          | Free-form text, often for ownership verification              |
| **TTL**                 | How long a DNS answer may be cached                           |
| **Registrar**           | Company you register the domain through                       |
| **DNS host**            | Service that answers DNS queries (here: Cloud DNS)            |
| **Delegation**          | Pointing a domain at a DNS host via nameservers               |
| **Resolver**            | Server that performs lookups on your behalf (`8.8.8.8`)       |
| **DNSSEC**              | Cryptographic authentication of DNS answers                   |
| **TLS/SSL certificate** | Proof a server is authorised for a hostname                   |
| **HSTS preload**        | Browser list forcing HTTPS (all `.dev` domains)               |
| **Load balancer**       | Front door: terminates TLS, routes by hostname/path           |
| **URL map**             | The load balancer's routing rules                             |
| **NEG**                 | Adapter connecting the load balancer to Cloud Run             |
| **Ingress**             | Which traffic sources a Cloud Run service accepts             |
| **Artifact Registry**   | Where container images are stored                             |
| **Service account**     | Non-human identity that GCP resources run as                  |
| **WIF**                 | Keyless auth letting GitHub Actions act as a service account  |
| **Terraform state**     | Terraform's record of what it created                         |
| **Module**              | Reusable grouping of Terraform resources                      |
