# CoreNet Protocol Specification v0.1

*Status: Draft. Subject to revision based on implementation experience.*

This document specifies the normative behavior of CoreNet routers, addressing, and control-plane conventions at the v0.1 milestone. Companion documents:

- [`README.md`](README.md) — the CoreNet proposal (informative, non-normative)
- [`meshcore-lxmf-encoding.md`](meshcore-lxmf-encoding.md) — MeshCore message type to LXMF field mapping (reference table)

---

## 1. Introduction

CoreNet is a routing and addressing layer for inter-zone bridging of MeshCore networks. It defines:

- A naming scheme for bridges and remote destinations
- A control-plane convention for discovery, conflict reporting, and bridge activation
- User-facing conventions for addressing remote peers from stock MeshCore clients
- Rules for bridge behavior that preserve MeshCore's flood-discipline and privacy properties

CoreNet is transport-agnostic. The v0.1 reference implementation uses LXMF over Reticulum as its wire transport; alternative transports (MQTT, TCP, ESP-NOW) conforming to the same addressing and control-plane conventions are permissible.

## 2. Conformance

This document uses the key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** as defined in RFC 2119.

An implementation is said to be **CoreNet v0.1 conformant** if it implements all MUST-level requirements and honors the privacy and conflict-handling rules in sections 10 and 11.

## 3. Terminology

**Router** — a process that bridges a local MeshCore mesh to one or more wide-area transports. Operates as a MeshCore companion to its local radio and as a participant on the wide-area plane.

**Bridge** — used interchangeably with *router*.

**Zone** — a MeshCore mesh served by one or more routers. Zones are identified by their routers, not by geography.

**Peer** — another router with which a given router has established a federation relationship.

**Manifest** — a router's signed list of callsign-to-pubkey bindings for nodes in its zone that have opted in to wide-area visibility.

**Identity** — a router's cryptographic keypair; its public-key-derived **hash** is the authoritative identifier.

**Control channel** — the well-known MeshCore channel `corenet-ctl` used for federation-plane signaling (Section 6).

**Callsign** — a human-readable name for a MeshCore node. May be an amateur radio callsign or any other operator-chosen label.

**Channel hash** — the cryptographic identifier of a MeshCore channel, derived from `(channel_name, channel_secret)`. Used in control-channel posts to reference a channel without disclosing its name.

**Publication state** — a channel's current disposition toward being listed publicly by name. Either *published* (listable) or *unpublished* (not listable). Default is unpublished.

**Channel notice** — a human-readable message posted by a router in a bridged channel to announce a state change (publish, unpublish, bridge activation, bridge expiration).

---

## 4. Identity and Naming

### 4.1 Router identity

Every router **MUST** hold a cryptographic identity providing (at minimum) an encryption keypair and a signing keypair. On the LXMF/Reticulum transport, this is a standard Reticulum identity.

The router's **identity hash** — a cryptographic hash of its public keys as computed by the underlying transport — is the **authoritative identifier** of the router. All other names for the router are labels.

Routers **MUST NOT** share identity keys across instances. High availability, if required, is achieved by operating multiple independent routers as federated peers.

### 4.2 Human-readable names

Routers advertise one or more human-readable names:

- A **fully-qualified router name**: a DNS-like string chosen by the operator, e.g., `bridge.lax.example.net`. Intended to be globally unique but not enforced.
- A **short tag**: a compact label, e.g., `LAX` or `US-WA`. Advisory only; collisions permitted.

Both forms are **labels**, not identities. No uniqueness is guaranteed at any naming level.

### 4.3 Name collision resolution

A router **MAY** observe multiple peers using identical names (short tag or fully-qualified). The router **MUST** resolve ambiguity using, in order:

1. **Hash distinction** — peers with identical names but different identity hashes are distinct peers. The router stores them separately, keyed by hash.
2. **Callsign-match disambiguation** — when a user supplies an ambiguous name, the router **SHOULD** route to the unique peer whose manifest contains the target callsign, if exactly one exists.
3. **Local aliasing** — the operator **MAY** configure locally-unique aliases for colliding peer names. Aliases are authoritative within that router's view and are not negotiated with peers.
4. **User disambiguation** — when automatic resolution is impossible, the router **MUST** reply to the user with the set of candidates and **MUST NOT** silently choose.

### 4.4 Fingerprint verification

Routers **SHOULD** expose identity-hash fingerprints (a truncated form suitable for human comparison, e.g., 4–8 bytes hex) in roster responses and control-channel posts. Operators **SHOULD** establish fingerprints for trusted peers out-of-band before federating.

---

## 5. Addressing

### 5.1 Qualified addresses

The canonical form of a remote address is:

```
@<callsign>@<router-name>
```

where `<router-name>` is either a short tag or a fully-qualified router name. Example:

```
@KD6O@SEA
@KD6O@bridge.sea.example.net
```

### 5.2 Grammar

```
address     = "@" callsign "@" router-name
callsign    = 1*32 ( ALPHA / DIGIT / "-" / "_" / "/" )
router-name = tag / fqrn
tag         = 1*16 ( ALPHA / DIGIT / "-" / "_" )
fqrn        = 1*64 ( ALPHA / DIGIT / "-" / "_" / "." )
```

Callsign case **SHOULD** be preserved but **MUST** be matched case-insensitively by routers.

### 5.3 Disambiguation

Routers **MUST** apply Section 4.3 resolution when the router-name is ambiguous. When ambiguity cannot be resolved, the router **MUST** return the error reply specified in Section 9.4.

---

## 6. Control Channel (`corenet-ctl`)

### 6.1 Channel identity

The control channel is a MeshCore channel with:

- **Name**: `corenet-ctl`
- **Secret**: established per federation, shared out-of-band among participating operators and users

The name is well-known; the secret **MUST NOT** be published in this specification or in public directories. Each federation of cooperating routers agrees on its own control-channel secret.

### 6.2 Access and trust

Any participant who holds the control-channel secret can read and post to it. The control channel is therefore an **opt-in, shared-trust plane**. Routers **SHOULD** subscribe to it by default; users **MAY** subscribe to observe federation activity.

### 6.3 Message signing

Every control-channel post by a router **MUST** be signed by the posting router's identity. Signatures cover the full text of the post including any timestamps.

Posts not signed by a recognized router identity **SHOULD** be ignored by other routers for control-plane purposes, though they remain visible to human observers.

### 6.4 Permitted message types

Routers **MAY** post the following message types to `corenet-ctl`:

- **Router online announcement** (Section 7.2)
- **Roster summary** (Section 7.3)
- **Bridge activation notice** (Section 8.2.3)
- **Identity conflict report** (Section 10.3)

All router posts on the control channel **MUST** reference channels only by hash, never by name (Section 8.1). Non-router participants (human users) **MAY** post freely for coordination purposes.

---

## 7. Roster and Discovery

CoreNet offers both pull-based and push-based mechanisms for users to learn what remote nodes and channels are visible. Routers **MUST** support pull queries and **SHOULD** support push summaries.

### 7.1 Pull: `who` query

A user sends a direct message to a router containing a query command as the entire message body:

```
who                    # all visible remote nodes
who <region>           # filter by router-name
who <callsign>         # look up a specific callsign
```

The router **MUST** reply with a direct message in a human-readable format. Response format is not strictly specified, but the router **SHOULD** include, for each matching entry:

- Callsign
- Router-name (short tag or fqrn)
- Time since last observation
- Identity fingerprint (truncated)

Example:

```
→ who CA
← 3 nodes in @CA:
    @KD6O@SEA   (3m)   [a1b2c3d4]
    @W7ABC@PDX  (12m)  [e5f6g7h8]
    @N2XYZ@SAC  (1h)   [i9j0k1l2]
```

When the response exceeds one MeshCore DM payload, the router **MUST** paginate or truncate; it **MUST NOT** silently drop entries.

### 7.2 Router online announcement

When a router starts up or reconnects, it **SHOULD** post a single signed announcement to the control channel containing its fully-qualified name, short tag, identity fingerprint, and a human-readable description of its zone.

### 7.3 Push: roster summary

A router **MAY** periodically post a summary of its visible remote roster to the control channel. When it does:

- Posts **MUST** be rate-limited to no more than one per 15 minutes per router, regardless of roster changes.
- Posts **MUST** be signed per Section 6.3.
- Posts **MUST NOT** include callsigns of nodes whose opt-in flags exclude them from wide-area visibility.
- Posts **SHOULD** include a summary count plus a pointer to the pull query for full detail, when the full roster would exceed one MeshCore channel message.

Routers **MUST NOT** include the callsign or identity of any user who triggered a roster-related action.

### 7.4 Pull: `channels` query

A user sends a direct message to a router containing:

```
channels               # all public channels this router bridges
channels <region>      # filter by region
```

The router **MUST** reply with a list of channels whose **publication state** (Section 8.4) is *published*. Channels in the *unpublished* state **MUST NOT** appear in the response, regardless of whether the router is actively bridging them.

The response **SHOULD** include, for each channel:

- Channel name
- Number of federated regions bridged
- Time the channel was most recently published
- Whether the publication is persistent or time-limited

Example:

```
→ channels
← 2 public channels at bridge.lax.example.net:
    corenet-wa       (bridged to 3 regions, published 2026-04-18)
    emergency-coord  (bridged to 6 regions, published 2026-01-12, persistent)
```

---

## 8. Channel Bridging

### 8.1 Channel identity

CoreNet bridging operates on **channel hashes** — cryptographic identifiers derived from `(channel_name, channel_secret)` — not on channel names. Two channels with the same name but different secrets are distinct and **MUST NOT** be bridged together.

Routers **MUST** use channel hashes in all control-plane posts. Channel names **MUST NOT** appear in any `corenet-ctl` post. Channel names **MAY** appear in in-channel notices (Section 8.6) and in responses to queries from authenticated channel members (Section 7.4).

### 8.2 Bridging modes

Routers **MUST** support nailed-up bridging; routers **MAY** support ad-hoc bridging.

#### 8.2.1 Nailed-up bridges

Nailed-up bridges are configured by the router operator and persist across router restarts. Operator configuration specifies, for each bridged channel, its name and secret. The router **MUST** begin forwarding traffic on configured channels as soon as it is operational.

Nailed-up configuration **MUST NOT** itself determine a channel's publication state. Publication state is established exclusively by in-channel messages (Section 8.4).

#### 8.2.2 Ad-hoc bridges

Ad-hoc bridges are activated by user command and expire after a specified duration. Command syntax, sent as a DM to the router:

```
bridge <channel-name> <duration>                    # activate
bridge <channel-name> <duration> to <region-list>   # scoped
unbridge <channel-name>                             # deactivate early
bridge-status                                       # list active bridges
```

Duration is specified as a bare number of minutes or with a suffix: `30m`, `2h`. The router **MUST** enforce a maximum duration; the recommended default is 2 hours.

A router **MUST** authorize ad-hoc bridge requests according to its operator's policy. Policies **MAY** include:

- Allowlist of authorized callsigns
- Rate limiting (e.g., N requests per hour per requester)
- Open (any authenticated user)

A router **MUST NOT** accept an ad-hoc bridge request for a channel whose secret it does not hold.

#### 8.2.3 Bridge activation notice

When a router activates or expires a bridge (nailed-up startup, ad-hoc activation, or ad-hoc expiration), it **MUST** post a signed notice to the control channel containing:

- Event type (`activate` / `expire`)
- Channel hash (never name)
- Posting router's identity
- For activations: expiration timestamp (or `persistent` for nailed-up)
- Timestamp of the event

The notice **MUST NOT** include the channel name, the requester's identity (if ad-hoc), or any other identifying information beyond the router and channel hash. This is a transparency mechanism for federation activity, not a discoverability mechanism for channel content (Section 7.4 covers the latter).

Example:

```
[CoreNet] activate: hash 3f7e2a19 by bridge.lax.example.net,
          expires 2026-04-19T16:00Z
```

### 8.3 Loop prevention

Every router that bridges a channel **MUST** maintain a *seen-tag set* for loop prevention. On receiving a channel message:

- From local RF: record its tag in the seen set; forward to the wide-area transport.
- From the wide-area transport: if its tag is in the seen set, drop it; otherwise record it and re-emit on local RF.

The seen-tag set **MUST** retain tags for at least 60 seconds. Routers **SHOULD** use a bounded LRU or time-based eviction to cap memory usage.

Message tags are 4-byte random values assigned by the originating radio (part of MeshCore's standard channel message format).

### 8.4 Publication state

A channel's publication state determines whether the router lists the channel by name in response to `channels` queries (Section 7.4). The two states are:

- **unpublished** (default) — the channel is bridged, but its name is not exposed in discovery queries
- **published** — the channel's name is exposed in discovery queries

Publication state is set exclusively by **in-channel control messages** posted by any channel member. Bridge operator configuration **MUST NOT** unilaterally establish publication state.

#### 8.4.1 Control message syntax

A channel member posts a message whose body is exactly one of:

```
::corenet publish::
::corenet publish <duration>::
::corenet unpublish::
```

where `<duration>` is an optional decimal number followed by `m` (minutes), `h` (hours), or `d` (days), e.g., `30m`, `2h`, `30d`.

Routers subscribed to the channel **MUST** parse every inbound channel message against this grammar and, on a match, treat it as a publication control event. Any channel member may post any control message; there is no hierarchy of authority within a channel.

#### 8.4.2 State transitions

On receiving a valid `publish` control message:

- The router **MUST** record the channel as published.
- If no `<duration>` was specified, the state is persistent — it does not expire on its own.
- If `<duration>` was specified, the state expires at `now + duration` and **MUST** automatically revert to unpublished at expiration.
- A later `publish` message **MUST** replace the earlier state, including extending or shortening its duration.

On receiving a valid `unpublish` control message:

- The router **MUST** record the channel as unpublished immediately.
- Unpublish is persistent; it does not expire.
- Unpublish **MUST** override any prior publish, including one marked persistent.

The most recent valid control message (by the channel's internal timestamp, or by the bridge's observation time when no timestamp is present) determines the current state. No voting, quorum, or seniority is applied.

#### 8.4.3 Implications of the flat trust model

Any channel member can change publication state. This is consistent with MeshCore's existing channel trust model: whoever holds the channel secret is a peer with full privileges, including the ability to read, post, and now to adjust publication.

Operators and users **SHOULD** understand that distributing the channel secret implicitly authorizes all its holders to act on the channel's publication state. CoreNet provides no protocol-level mechanism to restrict this to a subset of members.

### 8.5 Peer state gossip

When a router federates with a new peer, the two routers **SHOULD** exchange the current publication state for any channels both of them bridge, so that a late-joining router can learn the state without waiting for the next in-channel control message.

#### 8.5.1 Query and response

During or shortly after federation handshake, a router **MAY** send a *publication-state query* to a peer for each channel hash both bridge. The peer **MUST** respond with, for each queried channel hash:

- Current state (`published` or `unpublished`)
- Timestamp of the control message that established the current state
- If `published` with a duration, the expiration timestamp
- A copy of the signed control message that established the state, if available

The querying router **MUST** verify that any published-state message it receives was indeed posted in the channel (by confirming the message decrypts under the channel secret, which both parties hold).

#### 8.5.2 Convergence rule

If two routers disagree on current state, the router holding the control message with the latest timestamp wins. Both routers adopt that state.

A router **MUST NOT** trust peer-gossiped state alone for a channel whose secret it does not hold; the verification step in 8.5.1 prevents adoption of fabricated messages.

### 8.6 Channel notices

When a router processes a publication state change or a bridge activation/expiration for a channel, it **SHOULD** post a human-readable notice in the channel itself. The notice is intended to make state changes visible to all channel members regardless of their client capabilities.

#### 8.6.1 Events that trigger notices

A router **SHOULD** post a channel notice on:

- Successful processing of a `::corenet publish::` message
- Successful processing of a `::corenet unpublish::` message
- Activation of bridging for the channel (nailed-up startup or ad-hoc activation)
- Expiration or early termination of ad-hoc bridging

#### 8.6.2 Notice content

Notices are human-readable text. Routers **SHOULD** include:

- The event type
- The channel name (notices appear only within the channel, so its members already know the name)
- The responsible party's callsign for publish and unpublish events
- Timing details (expiration, duration)
- For publish and unpublish, a hint about how to reverse the action

Example notices:

```
[CoreNet] #corenet-wa is now publicly discoverable across the federation.
          Posted by @KD6O at 15:42 UTC. Any member may revert with
          ::corenet unpublish::

[CoreNet] #corenet-wa bridging activated for 30 minutes.
          Traffic will cross 3 federated regions until 16:12 UTC.

[CoreNet] #corenet-wa is no longer publicly discoverable.
          Reverted by @W7ABC at 16:08 UTC.
```

#### 8.6.3 Deduplication across bridges

Multiple routers bridging the same channel **MAY** all observe the same event and attempt to post notices. To avoid spam, each router **SHOULD**:

- Post at most one notice per event it observes
- Delay posting by a small random interval (e.g., 0–5 seconds)
- Suppress its own posting if another router's notice for the same event arrives first

A router **MUST** attribute notices to itself (the notice is posted under the router's MeshCore identity), so members can distinguish multiple notices and operators can verify which bridges observed the event.

---

## 9. Manual DM Routing

Stock MeshCore clients address remote peers by including a CoreNet address at the start of a direct message to a router.

### 9.1 Outbound convention

A user sends a DM to a router beginning with a CoreNet address:

```
@KD6O@SEA hey, how's the weather
```

The router **MUST** parse the leading address using the grammar in Section 5.2. On a successful parse:

- Strip the address and any single trailing space from the body.
- Resolve the address per Section 5.3.
- Forward the remaining text to the target router via the wide-area transport.

On a failed parse, the router **MUST** treat the message as a query or command intended for the router itself (Section 7.1, Section 8.2.2, Section 7.4).

### 9.2 Inbound delivery

When a router receives a wide-area message destined for a local user, it **MUST** deliver the message as a DM from itself to the user, with the source CoreNet address prefixed in brackets:

```
[@W5XYZ@LAX] hey, how's the weather
```

Recipient users see a DM from the router with the origin clearly marked in the text.

### 9.3 Reply context

When a user replies to a delivered inbound message without an explicit CoreNet address prefix, the router **MAY** interpret the reply as destined for the most recent remote sender to that user. Implementations that support this feature **MUST** disclose the inferred destination in their confirmation.

### 9.4 Error replies

When a router cannot resolve or deliver a message, it **MUST** reply to the originating user with a descriptive error. Error reply text is not specified, but **MUST** distinguish:

- Unknown destination (`@callsign@region` not found)
- Ambiguous destination (multiple matches; list them)
- Authorization denied (ad-hoc bridge request refused)
- Transport failure (temporary)

---

## 10. Identity Conflict Handling

### 10.1 Detection

A router **MUST** detect identity conflicts among its federated peers. A conflict exists when two peer announcements share the same identity hash but have different identity public keys.

### 10.2 Resolution policy

On detecting a conflict:

- The **incumbent** peer — the first one the router federated with — **MUST** be retained.
- The **latecomer** peer **MUST** be refused federation.
- The router **MUST NOT** silently select between them based on any other heuristic.
- The operator **MAY** manually override the resolution via local configuration.

### 10.3 Conflict reports

On detecting a conflict, the router **SHOULD** publish a signed conflict report to the control channel. The report **MUST** include:

- The colliding identity hash
- Identity fingerprints of both peers
- Timestamps of first observation of each
- Which peer was retained and which refused
- The reporting router's identity

Routers **SHOULD** deduplicate: do not re-publish a report for the same conflict pair already published by this router within the last hour.

Example report:

```
[CoreNet] Identity conflict at bridge.lax.example.net:
  hash a1b2c3d4 —
    pubkey fp e5f6g7h8 (seen 14:23:15Z via bridge.sac.alice.net) [retained]
    pubkey fp 9a0b1c2d (seen 15:47:02Z via bridge.sac.bob.net) [refused]
```

---

## 11. Privacy Requirements

### 11.1 Zero-hop ingress

A router **MUST NOT** re-broadcast on local RF any advertisement it received via the wide-area transport. Remote node visibility is available to users exclusively through roster queries and inbound DM delivery, never through RF advertisement injection.

### 11.2 Opt-in visibility

A router **MUST** consult each local contact's opt-in flags before including it in manifests exposed to peers or in roster responses. Contacts without wide-area opt-in **MUST NOT** appear in manifests, roster responses, or control-channel summaries.

### 11.3 Position precision

When a router includes coordinates in manifest entries or advertisements:

- Coordinates **MUST** be reduced to at most 6 decimal digits of fractional degree (approximately 100-meter resolution).
- The exact precision reduction is operator-configurable; 5 decimal digits (approximately 1-kilometer resolution) is the recommended default for public visibility.

### 11.4 Attribution disclosure rules

Attribution rules differ between the control channel and individual bridged channels, because the audiences differ.

**Control channel posts** reach every federation participant who holds the control-channel secret. A router **MUST NOT** include in any control-channel post the callsign, identity, or any other personally identifying information of a user who requested, triggered, or is otherwise associated with the action being reported. Bridge activation notices, roster summaries, and conflict reports identify only the router, never the user.

**In-channel notices** (Section 8.6) are visible only to members of the channel, who already share the channel secret and are therefore already trusted with the channel's contents. A router **MAY** include the responsible party's callsign in in-channel notices for publish, unpublish, or ad-hoc bridge-activation events. Attribution in this context is appropriate for social accountability among channel members.

A router **MUST NOT** cross-post attribution information from an in-channel notice to the control channel or to any other channel.

### 11.5 Channel privacy by default

Channels are unpublished by default (Section 8.4). A channel whose members have not explicitly posted a `::corenet publish::` control message **MUST NOT** appear by name in any `channels` query response, roster summary, or other discoverability surface.

Routers **MUST** treat the absence of a publication message as a positive privacy signal, not merely a neutral default. Traffic on unpublished channels is bridged normally (activation notices on the control channel still appear, by hash only per Section 8.2.3) but the channel's name is withheld from discovery.

### 11.6 Channel name confidentiality

Channel names **MUST NOT** appear in any post on the control channel, regardless of publication state. Channel hashes (Section 8.1) are the sole channel identifier on the control plane. Channel names appear only:

- In in-channel notices (visible only to members)
- In `channels` query responses (only for published channels)
- In direct interactions between a router and a user who has proved channel membership (e.g., by using the channel secret)

This rule ensures that the mere existence of bridging activity does not reveal what is being bridged to non-members.

---

## 12. Security Considerations

### 12.1 Operator trust

A CoreNet router is a message-forwarding endpoint. Operators of routers can observe, log, and modify messages passing through them. Users extending trust to a router accept the same operator-trust model as any repeater or broker. This is not different from the model users implicitly accept with MQTT brokers or IRC servers.

### 12.2 Identity compromise

If a router's identity key is compromised, no CoreNet mechanism can detect or mitigate this. The operator **MUST** generate a new identity, publish the new fingerprint out-of-band to federated peers, and re-establish trust relationships. The compromised identity **SHOULD** be considered burned; CoreNet provides no revocation mechanism at v0.1.

### 12.3 Control-channel leakage

The control channel is a shared-secret plane. Any participant can relay what they see. Operators **SHOULD NOT** include sensitive operational information in control-channel posts beyond what this specification requires. Posts are designed to be safe to relay.

### 12.4 Replay

Signed control-channel posts **SHOULD** include a timestamp and be rejected if the timestamp is implausible (more than 24 hours old or more than 5 minutes in the future). Routers **MAY** additionally track recent post hashes for replay detection.

### 12.5 Channel publication authority

The publication mechanism (Section 8.4) inherits MeshCore's flat channel trust model. Any member holding the channel secret can publish or unpublish the channel, and these actions are not restricted or prioritized by seniority, quorum, or other governance mechanism.

A malicious or compromised channel member can publicize the channel's name against the wishes of other members. Affected members can revert via `::corenet unpublish::` — the change is immediate and visible to all members via the channel notice mechanism — but cannot prevent initial disclosure if they were not present when the publish occurred.

Operators and users **SHOULD** consider channel secret distribution carefully. Any party granted the secret is thereby granted publication authority.

### 12.6 Known unresolved problems

v0.1 intentionally does not address:

- **Identity revocation** — no broadcast mechanism for retiring a compromised or obsolete identity.
- **Manifest integrity across transitive federation** — a router's trust in a peer's manifest does not extend automatically to that peer's peers.
- **Denial of service via ad-hoc bridge requests** — mitigated only by operator-configured rate limits.
- **Publication ping-pong** — repeated publish/unpublish cycles by disagreeing members. Visible but not arbitrated by the protocol.
- **Governance within a channel** — no mechanism for subsets of channel members to have elevated publication rights.

Future specification revisions may address these.

---

## 13. Transport

### 13.1 Reference transport

The v0.1 reference transport is LXMF over Reticulum. Message-type to LXMF field mappings are specified in [`meshcore-lxmf-encoding.md`](meshcore-lxmf-encoding.md).

### 13.2 Alternative transports

Implementations **MAY** use transports other than LXMF/Reticulum (MQTT, TCP, etc.) provided they preserve:

- Identity hash as the authoritative router identifier
- End-to-end addressability between routers
- Message integrity and sender authentication
- Adequate reliability for the message types carried

A router using an alternative transport **MUST** be able to federate with routers on other transports via a gateway that translates between them, or **MUST** clearly document its limited federation scope.

---

## 14. References

- **RFC 2119** — Key words for use in RFCs to Indicate Requirement Levels
- **Reticulum Network Stack** — https://reticulum.network/
- **LXMF** — Lightweight Extensible Message Format
- **MeshCore** — https://meshcore.co.uk/
- **CoreNet Proposal (README)** — informative companion to this specification
- **MeshCore–LXMF Encoding Table** — [`meshcore-lxmf-encoding.md`](meshcore-lxmf-encoding.md)

---

## Appendix A — Open questions for v0.2

The following are known gaps in v0.1 that future specification work should address:

1. **Manifest wire format and signature scheme.** v0.1 specifies that manifests are signed but does not mandate a specific format.
2. **Revocation.** Mechanism for retiring identities without social coordination.
3. **Transitive federation.** Rules for trusting peer-of-peer manifests.
4. **Transport bridging gateways.** Normative rules for gateways between LXMF and non-LXMF transports.
5. **Propagation node discovery.** Whether CoreNet mandates specific LXMF propagation node topology.
6. **Roster response format.** Currently unspecified beyond general shape; may benefit from a machine-readable variant.
7. **Channel publication governance.** Whether a subset of channel members can be designated as publication authorities, overriding the flat model.
8. **Notice suppression coordination.** Whether bridges should use a dedicated protocol (rather than random delay) to elect a single notice poster per event.

---

*End of CoreNet Protocol Specification v0.1.*
