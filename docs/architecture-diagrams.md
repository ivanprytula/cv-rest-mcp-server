# Architecture Diagrams (C4)

> **Sanitized copy.** Real project IDs, IPs, domains, and service-account names
> are replaced with `<PLACEHOLDERS>`. The operator's full-detail counterpart is
> `.agent/architecture-diagrams_local.md` (gitignored). **Edit both together** —
> see [AGENTS.md](../AGENTS.md#paired-documentation).

Visual model of the system, following the [C4 model](https://c4model.com/):
each level zooms in one step further.

| Level | Question it answers | Section |
| --- | --- | --- |
| 1. System Context | Who uses it, what does it talk to? | [↓](#1-system-context) |
| 2. Container | What are the deployable pieces? | [↓](#2-containers) |
| 3. Component | What is inside `api-core`? | [↓](#3-components-api-core) |
| — Deployment | Where does it physically run? | [↓](#4-deployment--gcp-infrastructure) |
| — Dynamic | How does a request flow? | [↓](#5-request-flows) |
| — CI/CD | How does code get there? | [↓](#6-cicd-pipelines) |

Concepts behind these (DNS, certificates, NEGs, ingress) are explained in
[infrastructure.md](infrastructure.md). Application internals are in
[architecture.md](architecture.md).

**Live values are recorded in [§7 Reference Data](#7-reference-data).** When
infrastructure changes, update that table and any diagram labels that repeat it.

---

## 1. System Context

Who and what the system interacts with.

```mermaid
flowchart TB
    visitor["<b>Visitor / Recruiter</b><br/><i>Person</i><br/>Reads the CV, downloads PDF"]
    operator["<b>Operator (you)</b><br/><i>Person</i><br/>Authors CV content, manages revisions"]
    agent["<b>LLM / MCP Client</b><br/><i>External system</i><br/>Claude Desktop, IDEs — calls MCP tools"]

    system["<b>CV REST/MCP Server</b><br/><i>Software System</i><br/>Renders a CV as JSON, HTML, themed PDFs;<br/>exposes MCP tools; tailors CVs to job descriptions"]

    gcs["<b>Google Cloud Storage</b><br/><i>External system</i><br/>CV source document (cv.json),<br/>static assets"]
    secrets["<b>Secret Manager</b><br/><i>External system</i><br/>JWT signing key,<br/>refresh-token pepper"]
    github["<b>GitHub Actions</b><br/><i>External system</i><br/>Builds images, deploys,<br/>applies Terraform"]

    visitor -->|"HTTPS — views CV,<br/>downloads PDF"| system
    operator -->|"HTTPS — logs in,<br/>manages revisions"| system
    agent -->|"MCP over HTTPS<br/>/mcp"| system

    system -->|"reads CV document"| gcs
    system -->|"reads secrets at startup"| secrets
    github -->|"deploys"| system

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef sys fill:#1168bd,stroke:#0b4884,color:#fff
    classDef ext fill:#999,stroke:#6b6b6b,color:#fff
    class visitor,operator,agent person
    class system sys
    class gcs,secrets,github ext
```

---

## 2. Containers

The deployable units. Each box is a separately built and released artifact.

```mermaid
flowchart TB
    visitor["Visitor"]:::person
    operator["Operator"]:::person
    agent["MCP Client"]:::person

    subgraph edge["Edge — Google Front End"]
        lb["<b>Global External ALB</b><br/><i><LB_IPV4>:443</i><br/>TLS termination, host/path routing"]:::infra
    end

    subgraph run["Cloud Run — europe-west1"]
        core["<b>api-core</b><br/><i>Python 3.14 / FastAPI + FastMCP</i><br/>CV API, HTML, PDF, MCP tools, auth<br/>port 8080"]:::container
        spa["<b>spa-origin</b><br/><i>nginx + React 19 SPA</i><br/>Operator console<br/>port 8080"]:::container
        games["<b>api-games</b><br/><i>Python / FastAPI</i><br/>Games service<br/>port 8080"]:::container
    end

    subgraph storage["Storage"]
        cvbucket[("<b>cv-data bucket</b><br/>cv.json — versioned")]:::store
        static[("<b>static bucket</b><br/>Vite-hashed assets<br/>fronted by Cloud CDN")]:::store
        sm[("<b>Secret Manager</b><br/>cv-jwt-signing-key<br/>cv-refresh-token-pepper")]:::store
        sqlite[("<b>SQLite</b><br/><i>in-container</i><br/>users, sessions")]:::store
    end

    visitor -->|"<APEX_DOMAIN><br/>www. / api."| lb
    operator -->|"app.<APEX_DOMAIN>"| lb
    agent -->|"api.<APEX_DOMAIN>/mcp"| lb

    lb -->|"Host: apex, www., api.<br/>→ NEG"| core
    lb -->|"Host: app.<br/>→ NEG"| spa
    lb -->|"Host: games.<br/>→ NEG"| games
    lb -->|"Host: app.<br/>Path: /assets/*"| static

    core -->|"reads (hot reload)"| cvbucket
    core -->|"env var injection"| sm
    core --> sqlite
    spa -.->|"XHR: api.<APEX_DOMAIN><br/>credentialed CORS"| lb

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef container fill:#1168bd,stroke:#0b4884,color:#fff
    classDef infra fill:#4b8bbe,stroke:#2d5c85,color:#fff
    classDef store fill:#6b6b6b,stroke:#4a4a4a,color:#fff
```

> **Note the dotted line.** The SPA is served from `app.` but calls the API at
> `api.` — a cross-origin request. This is why `api-core` runs credentialed CORS
> pinned to the SPA origin, and why the refresh cookie is host-prefixed.

---

## 3. Components (api-core)

Inside the `api-core` container. Middleware runs **outside-in**: the first
listed is outermost and sees the request first.

```mermaid
flowchart TB
    req(["Incoming HTTPS request"]):::ext

    subgraph mw["Middleware stack — outside-in"]
        direction TB
        sec["<b>SecurityHeaders</b><br/>CSP, HSTS, nosniff"]:::comp
        guard["<b>Guard</b><br/>allowlist / blocklist /<br/>failban / service hours"]:::comp
        cors["<b>CredentialedCORS</b><br/>pinned to SPA origin"]:::comp
        jwt["<b>JWTAuth</b><br/>HS256 bearer validation"]:::comp
    end

    subgraph routing["Routing"]
        routes["<b>routes.py</b><br/>/ /health /cv /cv/html<br/>/cv/pdf /cv/tailor"]:::comp
        mcp["<b>FastMCP</b><br/>/mcp — tool surface"]:::comp
        authr["<b>auth routes</b><br/>login, refresh, logout"]:::comp
    end

    subgraph domain["Domain services"]
        pdf["<b>PdfService</b><br/>LRU cache + bounded<br/>thread pool (WeasyPrint)"]:::comp
        renderer["<b>renderer</b><br/>Jinja2 + theme CSS"]:::comp
        tailor["<b>matching/tailor</b><br/>JD → tailored CV"]:::comp
        users["<b>UserService</b><br/>auth, revisions"]:::comp
    end

    subgraph data["Data access"]
        cvsrc["<b>CvSource</b><br/>GCS or file,<br/>generation-checked reload"]:::comp
        store["<b>user_store</b><br/>async SQLAlchemy"]:::comp
    end

    gcs[("GCS cv.json")]:::extstore
    db[("SQLite")]:::extstore

    req --> sec --> guard --> cors --> jwt
    jwt --> routes & mcp & authr

    routes --> pdf & renderer & tailor
    mcp --> tailor & renderer
    authr --> users

    pdf --> renderer
    renderer --> cvsrc
    tailor --> cvsrc
    users --> store

    cvsrc --> gcs
    store --> db

    classDef comp fill:#1168bd,stroke:#0b4884,color:#fff
    classDef ext fill:#08427b,stroke:#052e56,color:#fff
    classDef extstore fill:#6b6b6b,stroke:#4a4a4a,color:#fff
```

---

## 4. Deployment — GCP Infrastructure

Physical placement, and which Terraform module owns each resource.

```mermaid
flowchart TB
    subgraph internet["Internet"]
        browser["Browser"]:::ext
        resolver["Public resolver<br/>8.8.8.8 / 1.1.1.1"]:::ext
    end

    subgraph registrar["<registrar> — Registrar"]
        ns["<b>Nameserver delegation</b><br/>→ ns-cloud-a1..a4<br/>.googledomains.com"]:::reg
    end

    subgraph gcp["GCP project: <PROJECT_ID> (<PROJECT_NUMBER>)"]
        subgraph dnsmod["module.dns"]
            zone["<b>Cloud DNS zone</b><br/><DNS_ZONE><br/>DNSSEC: on (NSEC3)<br/>5 × A → LB, TTL 300"]:::tf
        end

        subgraph edgemod["module.edge_lb — global"]
            ip["<b>Global static IP</b><br/><LB_IPV4>"]:::tf
            certs["<b>5 × Managed SSL certs</b><br/>apex, www, api, app, games"]:::tf
            proxy["<b>Target HTTPS proxy</b><br/>cv-edge-https-proxy"]:::tf
            umap["<b>URL map</b><br/>cv-edge-url-map<br/>host rules + path matchers"]:::tf
            bsvc["<b>Backend services</b><br/>one per NEG"]:::tf
            bbucket["<b>Backend bucket</b><br/>Cloud CDN"]:::tf
        end

        subgraph runmod["module.run — europe-west1"]
            neg1["NEG api-core-neg"]:::tf
            neg2["NEG spa-origin-neg"]:::tf
            neg3["NEG api-games-neg"]:::tf
            svc1["<b>api-core</b><br/>SA: api-core-runtime@<br/>ingress: internal-and-cloud-load-balancing"]:::tf
            svc2["<b>spa-origin</b><br/>SA: spa-origin-runtime@"]:::tf
            svc3["<b>api-games</b><br/>SA: api-games-runtime@"]:::tf
        end

        subgraph iammod["module.iam_secrets"]
            ar["<b>Artifact Registry</b><br/>cv-images (europe-west1)"]:::tf
            sas["<b>Service accounts</b><br/>3 × runtime + deployer"]:::tf
            secretsr[("Secret Manager<br/><i>created by bootstrap script</i>")]:::manual
        end

        subgraph wifmod["module.github_wif"]
            wif["<b>WIF pool + provider</b><br/>trust: repo == <GITHUB_OWNER>/<REPO>"]:::tf
        end

        buckets[("<b>GCS</b><br/>cv-data (bootstrap)<br/>static (module.static_bucket)<br/>dev-tfstate (bootstrap)")]:::mixed
    end

    gha["GitHub Actions"]:::ext

    browser -->|"1. resolve"| resolver
    resolver -->|"2. NS lookup"| ns
    ns -->|"3. authoritative"| zone
    zone -->|"4. <LB_IPV4>"| browser
    browser -->|"5. HTTPS :443"| ip

    ip --> proxy
    certs -.->|"terminate TLS"| proxy
    proxy --> umap
    umap --> bsvc
    umap -->|"/assets/*"| bbucket
    bsvc --> neg1 & neg2 & neg3
    neg1 --> svc1
    neg2 --> svc2
    neg3 --> svc3
    bbucket --> buckets

    gha -->|"OIDC token"| wif
    wif -->|"impersonate deployer@"| sas
    gha -->|"push images"| ar
    ar -->|"pull"| svc1 & svc2 & svc3
    svc1 --> secretsr & buckets

    classDef tf fill:#7B42BC,stroke:#5a2f8c,color:#fff
    classDef manual fill:#d97706,stroke:#a35a05,color:#fff
    classDef mixed fill:#9a6bbf,stroke:#6d4a87,color:#fff
    classDef ext fill:#6b6b6b,stroke:#4a4a4a,color:#fff
    classDef reg fill:#2d6a4f,stroke:#1b4332,color:#fff
```

**Legend** — <span>🟣 purple</span> = Terraform-managed · 🟠 orange = created by
`scripts/deploy-cloud-run.sh` (bootstrap) · 🟪 mixed = some of each · 🟢 green =
outside GCP.

---

## 5. Request Flows

### 5.1 Visitor requests a themed PDF

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant D as Cloud DNS
    participant LB as Global ALB
    participant C as api-core
    participant G as GCS

    B->>D: A? api.<APEX_DOMAIN>
    D-->>B: <LB_IPV4> (TTL 300)
    B->>LB: TLS ClientHello (SNI: api.<APEX_DOMAIN>)
    LB-->>B: cert cv-edge-cert-api-<DNS_ZONE>
    B->>LB: GET /cv/pdf?theme=modern
    LB->>C: forward via api-core-neg

    Note over C: Guard → CORS → JWT middleware
    C->>C: rate-limit check (PDF is CPU-bound)
    C->>G: read cv.json (if generation changed)
    G-->>C: CV document
    C->>C: cache hit? else render in thread pool
    C-->>LB: 200 application/pdf
    LB-->>B: 200 application/pdf
```

### 5.2 Operator logs into the SPA (cross-origin)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant LB as Global ALB
    participant S as spa-origin
    participant C as api-core

    B->>LB: GET app.<APEX_DOMAIN>/
    LB->>S: via spa-origin-neg
    S-->>B: index.html + JS
    B->>LB: GET app.<APEX_DOMAIN>/assets/*
    LB-->>B: from CDN bucket (immutable, hashed)

    Note over B,C: SPA now calls a different origin
    B->>LB: OPTIONS api.<APEX_DOMAIN>/auth/login
    LB->>C: preflight
    C-->>B: CORS allow (origin pinned to app.)
    B->>LB: POST /auth/login (credentials)
    LB->>C: forward
    C->>C: verify password, sign HS256 JWT
    C-->>B: access token + __Host- refresh cookie
```

### 5.3 What failed before DNS delegation

Recording the failure mode, since it was non-obvious:

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant SQ as <registrar> DNS
    participant CD as Cloud DNS
    participant G as Google CA

    Note over CD: Zone had correct records all along
    B->>SQ: A? api.<APEX_DOMAIN>
    SQ-->>B: NXDOMAIN — record not in registrar's set
    Note over B,CD: Cloud DNS never consulted:<br/>no delegation pointed at it

    G->>SQ: validate api.<APEX_DOMAIN> → LB?
    SQ-->>G: does not resolve
    Note over G: cert status FAILED_NOT_VISIBLE<br/>(a DNS fault, surfaced as a cert error)
```

---

## 6. CI/CD Pipelines

Two path-filtered workflows enforcing: **Terraform owns the platform, the app
pipeline owns the released artifact.**

```mermaid
flowchart LR
    subgraph dev["Developer"]
        push["git push"]:::ext
    end

    push --> gate{"Which paths<br/>changed?"}:::decision

    subgraph appwf["deploy-app.yml"]
        direction TB
        a1["code-quality<br/>ruff + ty"]:::job
        a2["tests<br/>410 pytest"]:::job
        a3["build<br/>3 images → Artifact Registry<br/>tagged :git-sha"]:::job
        a4["deploy<br/>gcloud run deploy ×3"]:::job
        a5["verify"]:::job
        a1 --> a2 --> a3 --> a4 --> a5
    end

    subgraph infrawf["ci-cd.yml"]
        direction TB
        i1["terraform-quality<br/>tflint + checkov"]:::job
        i2["cost-estimate<br/>Infracost, $100 budget"]:::job
        i3["terraform-plan<br/>→ job summary + PR comment<br/>→ artifact (5 days)"]:::job
        i4{{"production environment<br/>APPROVAL GATE"}}:::gate
        i5["terraform-apply<br/>applies the reviewed plan"]:::job
        i1 --> i2 --> i3 --> i4 --> i5
    end

    gate -->|"app/ frontend/<br/>services/ Dockerfiles"| appwf
    gate -->|"terraform/**"| infrawf

    a4 -.->|"sets image tag only"| note1["Cloud Run services"]:::ext
    i5 -.->|"sets everything except<br/>the image tag"| note1

    classDef job fill:#1168bd,stroke:#0b4884,color:#fff
    classDef gate fill:#d97706,stroke:#a35a05,color:#fff
    classDef decision fill:#4b8bbe,stroke:#2d5c85,color:#fff
    classDef ext fill:#6b6b6b,stroke:#4a4a4a,color:#fff
```

The dotted lines are the crux: both pipelines write to the same Cloud Run
services but own **disjoint fields**. `lifecycle { ignore_changes = [image] }`
in `modules/cloud_run_service` is what keeps them from reverting each other.

---

## 7. Reference Data

Live values. Verify with the commands in the last column.

### Network

| Item | Value | Verify |
| --- | --- | --- |
| GCP project | `<PROJECT_ID>` (number `<PROJECT_NUMBER>`) | `gcloud config get-value project` |
| Region | `europe-west1` | — |
| Load balancer IPv4 | `<LB_IPV4>` | `terraform output load_balancer_ipv4` |
| Apex domain | `<APEX_DOMAIN>` | — |
| Registrar | registrar | — |
| DNS host | Cloud DNS, zone `<DNS_ZONE>` | `gcloud dns managed-zones list` |
| Nameservers | `ns-cloud-a1..a4.googledomains.com` | `terraform output nameservers` |
| Record TTL | 300s | `gcloud dns record-sets list --zone=<DNS_ZONE>` |
| DNSSEC | signing on (NSEC3); DS record **not yet published** | `gcloud dns dns-keys list --zone=<DNS_ZONE>` |

### Hostname routing

| Hostname | Workload | Notes |
| --- | --- | --- |
| `<APEX_DOMAIN>` | `api-core` | apex |
| `www.<APEX_DOMAIN>` | `api-core` | |
| `api.<APEX_DOMAIN>` | `api-core` | REST + `/mcp` |
| `app.<APEX_DOMAIN>` | `spa-origin` | `/assets/*` → CDN bucket |
| `games.<APEX_DOMAIN>` | `api-games` | |

### Cloud Run services

| Service | Dockerfile | Runtime SA | Port | Ingress |
| --- | --- | --- | --- | --- |
| `api-core` | `Dockerfile` | `api-core-runtime@…` | 8080 | internal-and-cloud-load-balancing |
| `spa-origin` | `frontend/Dockerfile` | `spa-origin-runtime@…` | 8080 | internal-and-cloud-load-balancing |
| `api-games` | `services/games/Dockerfile` | `api-games-runtime@…` | 8080 | internal-and-cloud-load-balancing |

Direct `*.run.app` URLs return **404 by design** — the ingress setting requires
traffic to arrive via the load balancer.

### Images and identity

| Item | Value |
| --- | --- |
| Artifact Registry | `europe-west1-docker.pkg.dev/<PROJECT_ID>/cv-images` |
| Image tag scheme | `<service>:<short-git-sha>` plus `:latest` |
| CI deployer SA | `deployer@<PROJECT_ID>.iam.gserviceaccount.com` |
| WIF provider | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/gh-actions` |
| WIF trust condition | `assertion.repository == '<GITHUB_OWNER>/<REPO>'` |
| Terraform state | `gs://<PROJECT_ID>-dev-tfstate`, prefix `terraform/state` |

> The `GCP_DEPLOY_SA` GitHub secret **must** name `deployer@`. Two older
> deployer accounts (`<PROJECT_ID>-deployer@`, `cv-ivanprytula-deployer@`)
> still exist unmanaged — see [infrastructure.md §7](infrastructure.md#7-identity-how-ci-talks-to-gcp-without-keys).

### Terraform modules

| Module | Owns |
| --- | --- |
| `gcp_apis` | API enablement (all but `cloudresourcemanager`) |
| `iam_secrets` | Service accounts, IAM bindings, Artifact Registry |
| `github_wif` | WIF pool, OIDC provider, impersonation bindings |
| `cloud_run_service` | One Cloud Run service + its serverless NEG |
| `edge_lb` | Global IP, SSL certs, URL map, proxy, backends |
| `dns` | Managed zone + A records |
| `static_bucket` | CDN origin bucket |
| `uploads` | Private user-content bucket (**currently disabled**) |
| `cloud_armor` | Edge rate limiting (**currently disabled**) |
| `org_policies` | Project guardrails (**currently disabled**) |

---

## Editing these diagrams

Mermaid renders natively on GitHub and in most IDEs. To iterate quickly, paste a
block into the [Mermaid Live Editor](https://mermaid.live).

Conventions used here:

- `flowchart TB` for structure, `sequenceDiagram` for flows
- `classDef` for consistent colouring; purple = Terraform-managed
- `<br/>` for line breaks inside labels
- Dotted arrows (`-.->`) for indirect or cross-origin relationships

When infrastructure changes, update **§7 first** — it is the single place values
are recorded — then any diagram labels repeating them.
