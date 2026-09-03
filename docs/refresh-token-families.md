# Refresh-token families

How revocation works for this service's JWTs, and what "revoking a family"
actually kills.

> Implemented in `services/portfolio/auth/refresh_token_service.py` (application),
> `refresh_token_repository.py` (port + adapter), and `refresh_token_row.py`
> (ORM). Postgres-backed since ADR-023 PR5; previously an in-memory,
> single-process store.

## The problem

Access tokens are stateless JWTs — the server verifies a signature and asks no
database. That is the point, and it is also why an issued access token **cannot
be withdrawn**: nothing is consulted that could say "no".

The standard answer is not to make access tokens revocable, but to keep them
short-lived and put the revocable state on the *refresh* token instead.

## Families are a chain, not a set

One login creates one **family**. Each refresh **replaces** the family's current
token, so at any moment exactly one refresh token in the lineage is valid:

```text
login        -> R1     family_id = hash(R1), current_hash = hash(R1)
refresh(R1)  -> R2     current_hash = hash(R2)    R1 now dead-but-remembered
refresh(R2)  -> R3     current_hash = hash(R3)    R2 now dead-but-remembered
```

"Family" therefore means *successive generations of one credential*, not a set
of sibling tokens held at once. In normal operation nobody ever holds two live
refresh tokens from one family.

## Why old hashes are kept

`refresh_token_index` records **every hash ever issued** against its family, not
just the current one. This is what makes replay detection possible.

Delete the old hash on rotation instead, and a replayed R1 looks merely
*unknown* — indistinguishable from garbage input. Keeping it turns "unknown
token" into "known-stolen token".

Because nobody legitimately holds two live tokens from one family, a second use
of a rotated-away token is unambiguous evidence that a copy exists somewhere it
should not. The server cannot tell which of the two parties is the thief, so the
only safe response is to kill the whole lineage — including the currently-valid
R3.

## What revocation touches

Revocation is one boolean on one row (`refresh_token_families.revoked`). No
access token is touched, because none is stored.

| Token | Effect of family revocation |
| --- | --- |
| Refresh tokens in that family (R1…Rn) | Dead immediately — next `/refresh` returns 401 |
| Access token already issued | **Still valid** until it expires (≤ `access_token_ttl_minutes`) |
| Other families for the same user | Untouched — a login on another device keeps working |

Two consequences worth being explicit about:

- **Revocation is eventual for access tokens**, bounded by their TTL. That is
  the accepted cost of keeping them stateless.
- **Scope is the family, not the user.** Logging in on a phone and a laptop
  creates two independent families; theft detected on one does not log the other
  out. "Log out everywhere" would be a separate operation (revoke all families
  `WHERE subject = :username` — the `subject` index supports it, nothing calls
  it today).

## Concurrency

`rotate()` puts the "is this the current token, and is the family live?"
predicate in the UPDATE's `WHERE` clause rather than in a preceding `SELECT`:

```python
update(RefreshTokenFamilyRow).where(
    RefreshTokenFamilyRow.family_id == family_id,
    RefreshTokenFamilyRow.current_hash == presented_hash,
    RefreshTokenFamilyRow.revoked.is_(False),
).values(current_hash=new_hash)
```

Two concurrent refreshes presenting the same token cannot both win: exactly one
UPDATE matches a row, the other sees `rowcount == 0`. A `SELECT`-then-`UPDATE`
pair would let both pass the check and defeat detection.

The loser is treated as a replay (the family is revoked) rather than forgiven —
two simultaneous uses of one refresh token is the stolen-token signature whether
they arrive microseconds or hours apart.

The in-memory predecessor used a `threading.Lock` for this, which only ever
covered a single process. With more than one Cloud Run instance live, instance B
had no record of instance A's rotations: legitimate refreshes failed
unpredictably, and replay detection could not fire across instances at all.

## Failure policy: fail closed

Unlike `RevisionService` (which degrades to a file fallback on DB error), this
service lets exceptions propagate. Returning a "not valid" sentinel on an outage
would be indistinguishable from a real auth decision, and silently treating a
database hiccup as a successful one would bypass replay detection entirely.

## Is this standard?

Yes. Refresh-token rotation with reuse detection is what
[RFC 9700](https://datatracker.ietf.org/doc/rfc9700/) §4.14.2 (OAuth 2.0
Security Best Current Practice) recommends for public clients, and what Auth0,
Okta and Keycloak ship. RFC 9700 gives sender-constrained tokens
([DPoP](https://datatracker.ietf.org/doc/html/rfc9449), mTLS) as the other
acceptable answer.

Alternatives considered and rejected:

| Approach | Why not |
| --- | --- |
| JWT denylist (`jti` blocklist) | Puts a datastore read on **every request** — the exact cost stateless JWTs exist to avoid — to close a window short TTLs already bound |
| Server-side sessions / allowlist | Instant revocation, but then the token is a session ID with extra steps |
| Reference tokens + introspection (RFC 7662) | Instant revocation, at a network hop per request |
| Sender-constrained (DPoP / mTLS) | Strongest option; meaningfully more client-side complexity than this service needs today |

If instant global logout is ever needed, the cheap move is a `token_version`
column on the user checked **on refresh only** — not a denylist on the hot path.

## Known limitation

`refresh_token_index` gains a row per rotation and nothing prunes it. At
single-operator scale the growth is negligible; a periodic `DELETE` of families
older than `refresh_token_ttl_days` would cascade the index rows away
(`ON DELETE CASCADE` is already in place).
