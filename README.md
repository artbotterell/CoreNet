# Proposal: LXMF as an Interoperability Plane for MeshCore Wide-Area Bridging

*Draft for community discussion. Acknowledges prior art, addresses known objections, and describes an additive architecture — not a replacement for existing bridging work.*

---

## Motivation

MeshCore provides reliable, low-power LoRa mesh communication within a region. Its bounded range is a feature, not a limitation: a dense local mesh is resilient, self-contained, and independent of external infrastructure.

But operators in different regions, or groups separated by terrain or distance, cannot currently reach each other, and the existing bridging work has fragmented along transport lines: some projects bridge over MQTT, some over ESP-NOW, some over Bluetooth via Bitchat, some are exploring Reticulum. Each bridge today is a point-to-point translation. A node bridged to MQTT cannot reach a node bridged to Bitchat without a second custom adapter.

This proposal describes an architectural pattern in which **LXMF serves as a common interoperability plane**, with lightweight adapters for each wide-area transport (MQTT, Reticulum native, Bitchat, TCP, etc.). The goals are to:

1. **Preserve the local RF medium.** No WAN housekeeping should appear on LoRa.
2. **Preserve existing investments.** MQTT bridges, ESP-NOW bridges, and Bitchat bridges should continue to work — and should be able to reach each other.
3. **Make bridge operation opt-in, auditable, and ham-legal where applicable.**
4. **Draw from the hard lessons of the Meshtastic MQTT trajectory** rather than relearning them.

---

## Prior Art

This proposal is not a greenfield design. The following projects and discussions have shaped the problem space; readers are encouraged to review them.

### Existing MeshCore Bridging Projects

- **[jmead/Meshcore-Repeater-MQTT-Gateway](https://github.com/jmead/Meshcore-Repeater-MQTT-Gateway)** — ESP32 firmware acting as both MeshCore repeater and MQTT bridge. Introduced hierarchical regional topic namespaces (`MESHCORE/AU/NSW`), TLS, and wildcard subscription as the de-facto pattern for MeshCore-over-MQTT.
- **[ipnet-mesh/meshcore-mqtt](https://github.com/ipnet-mesh/meshcore-mqtt)** — host-side Python bridge over serial/BLE/TCP, with TLS and rate limiting.
- **[73mesh.com MQTT bridge tutorial](https://www.73mesh.com/2025/11/12/mqttServer.html)** — Pi-plus-LoRa-Node DIY pattern.
- **Juraj Bednar's [Bitchat↔MeshCore bridge](https://juraj.bednar.io/en/blog-en/2026/01/18/bridging-bitchat-and-meshcore-resilient-communication-when-you-need-it-most/)** — cross-protocol bridge firmware joining a Bluetooth chat mesh to a MeshCore LoRa mesh.
- **MeshCore native Bridge primitives** — the firmware already supports ESP-NOW and RS-232 bridges as specialised repeater nodes. New transports (MQTT, Reticulum, Bitchat) are extensions of this pre-existing bridge abstraction.

### Relevant Open RFCs

- **[MeshCore Discussion #1736 — Reticulum Network Stack as Decentralized Backhaul](https://github.com/meshcore-dev/MeshCore/discussions/1736)** — the existing Reticulum-as-backhaul proposal. Notes the concrete harm of two meshes (LAX, SEA) getting inadvertently joined over IP with cross-continental advert leakage. This proposal treats that incident as the governing cautionary example.
- **[Meshtastic Discussion #460 — Reticulum vs MQTT](https://github.com/orgs/meshtastic/discussions/460)** — parallel debate in the sibling project.
- **[MeshCore Discussion #2093 — flooded adverts](https://github.com/meshcore-dev/MeshCore/discussions/2093)** — existing scaling pain in advert handling that bridging must not worsen.

### Meshtastic's MQTT Trajectory

Meshtastic's public MQTT broker was restructured in August 2024 after it became clear that third-party mesh-map sites were harvesting location data from "regionally shared" channels that users thought were local. This is the cautionary tale every subsequent bridging proposal must answer. Key references: [Recent Public MQTT Broker Changes](https://meshtastic.org/blog/recent-public-mqtt-broker-changes/), [Routing Etiquette Discussion #47](https://github.com/orgs/meshtastic/discussions/47).

---

## Guiding Principles

1. **The local RF medium is sacred.** No WAN-originated traffic appears on LoRa by default. Bridged contacts live at the application layer only.
2. **Local-first is a cultural commitment, not only a technical one.** The mesh works when the backhaul fails. Bridging is optional, opt-in, and additive.
3. **Adverts do not cross bridges by default.** The LAX↔SEA incident in Discussion #1736 is treated as settled precedent: this is a *messaging* bridge, not a *discovery* bridge. Discovery across regions is pull-based and explicit.
4. **Identity is cryptographic, not administrative.** MeshCore nodes are already identified by Ed25519 keys. Bridge-plane identity derives from these.
5. **Safe by default.** Users do not read manuals. Position precision, region scope, and propagation defaults must be safe even when nothing is configured.
6. **ISM-first, amateur-radio-friendly.** MeshCore generally operates on license-free ISM bands (e.g., 868 MHz in Europe, 915 MHz in the Americas), where there are no content, identification, or encryption restrictions beyond the usual ISM power and duty-cycle rules. **The default assumptions of this proposal are ISM assumptions.** Some licensed operators additionally run MeshCore at higher power under amateur radio rules on amateur allocations that overlap ISM (notably the 33 cm band in ITU Region 2); those deployments carry their own regulatory constraints, addressed separately below as an opt-in configuration.
7. **No upstream firmware changes required.** Bridges operate as companions. Firmware-level changes may be proposed later but are not on the critical path.

---

## What is Reticulum, and Why LXMF?

[Reticulum](https://reticulum.network) is a cryptography-based networking stack designed for unreliable, low-bandwidth, heterogeneous transports. [LXMF](https://github.com/markqvist/LXMF) (Lightweight Extensible Message Format) is the messaging protocol layered on top of Reticulum: authenticated, encrypted, store-and-forward-capable, and transport-agnostic.

LXMF is used here as an **interoperability format**, not as a mandated transport. The reasons:

- **Transport-neutral.** An LXMF message can traverse Reticulum over TCP, serial, LoRa backbone, I2C, Bluetooth, or any combination — and can also be carried opaquely inside an MQTT message, a Bitchat payload, or any other envelope that an adapter defines.
- **Cryptographically addressed.** LXMF destinations are derived from public keys, so identity survives transport changes without a naming service.
- **Store-and-forward native.** Offline delivery works without extra machinery.
- **Signed metadata.** Sender authentication is standard — useful generally, and specifically important for the subset of deployments that operate under amateur radio rules, where authentication is permitted but encryption is not.
- **Already proposed as MeshCore backhaul.** Discussion #1736 has laid groundwork; this proposal extends it with an adapter pattern.

This proposal does **not** argue that Reticulum should replace MQTT. MQTT works, has existing deployments, and has strengths (low resource overhead, widely understood operational model). LXMF is proposed as the *common envelope* so that MQTT-bridged nodes and Reticulum-bridged nodes can reach each other without custom gateways for every pair.

---

## Architecture Overview

```
┌─────────────── Region A ────────────────┐   ┌─────────────── Region B ──────────────┐
│                                         │   │                                        │
│  Companion app ─── companion protocol   │   │   companion protocol ─── Companion app │
│                      │                  │   │                 │                      │
│                      ▼                  │   │                 ▼                      │
│              [Bridge Daemon]            │   │         [Bridge Daemon]                │
│               │           │             │   │          │           │                 │
│         local radio   LXMF core         │   │    LXMF core     local radio           │
│          (serial/       │               │   │        │          (serial/             │
│           BLE/TCP)      │               │   │        │           BLE/TCP)            │
│                         │               │   │        │                               │
│                    ┌────┴────┐          │   │   ┌────┴────┐                          │
│                    │ Adapters│          │   │   │ Adapters│                          │
│                    └────┬────┘          │   │   └────┬────┘                          │
│                         │               │   │        │                               │
└─────────────────────────┼───────────────┘   └────────┼───────────────────────────────┘
                          │                            │
                   ╔══════╧════════════════════════════╧═══════╗
                   ║  Wide-area transports (any combination):  ║
                   ║  • Reticulum native (TCP/I2P/RNode/serial)║
                   ║  • MQTT brokers (regional, federated)     ║
                   ║  • Bitchat mesh                           ║
                   ║  • Ad-hoc TCP/HAMNET                      ║
                   ╚═══════════════════════════════════════════╝
```

### Bridge Daemon

A software process that runs on any always-on computer (Raspberry Pi, local server, cloud VM). It connects to the local MeshCore radio as a companion, runs an LXMF core, and loads one or more adapters. It:

- Intercepts outbound messages destined for remote nodes and hands them to the appropriate adapter.
- Receives inbound messages via adapters and synthesises received-message push notifications to the local companion app.
- Maintains a **contact manifest** (a signed, opt-in list of locally reachable nodes) available for remote bridges to query.
- Registers itself as a single gateway contact on the local LoRa mesh (one advertisement per bridge, regardless of how many remote nodes are reachable through it).

### Adapters

Each adapter converts between LXMF and a specific transport:

| Adapter | Transport | Notes |
|---|---|---|
| `lxmf-reticulum` | Reticulum native | Most direct; uses Reticulum Transport instances on TCP, LoRa backbone (RNode), I2P, etc. |
| `lxmf-mqtt` | MQTT broker | Wraps LXMF messages in MQTT payloads using jmead-style regional topic hierarchy (`MESHCORE/<cc>/<region>/lxmf`). Existing MQTT bridges can coexist by subscribing to both raw and LXMF-wrapped topics. |
| `lxmf-bitchat` | Bitchat BLE mesh | Carries LXMF envelopes as Bitchat payloads; enables Bluetooth-only inter-region hops. |
| `lxmf-tcp` | Direct TCP/HAMNET | Simple point-to-point links between two bridges. |
| `lxmf-esp-now` | ESP-NOW | For short-haul out-of-band bridging that reuses the firmware's existing ESP-NOW bridge primitive. |

A bridge loads whichever adapters are relevant to its deployment. Most bridges will run two (e.g., Reticulum + MQTT for backward compatibility with existing MQTT deployments).

### What Crosses the Bridge

| Traffic type | Default behaviour |
|---|---|
| Direct messages (DM) | Forwarded on demand to the addressed node |
| Channel messages | Forwarded only to bridges explicitly subscribed to the same channel secret |
| Node advertisements | **Not forwarded** by default; available via pull-based manifest query |
| Position data | Included in manifests only if the node has opted in; precision reduced by configuration |
| Telemetry | Forwarded only in response to explicit requests |
| Path-discovery / neighbour queries | Answered locally; remote nodes shown with maximum path-length marker |
| Bridge gateway advert (one per bridge) | Broadcast on local LoRa as normal contact |

---

## Node Identity and Addressing

MeshCore nodes are identified by 32-byte Ed25519 public keys. LXMF destinations are derived from Curve25519 identities.

**Proposed mapping:** each MeshCore node's Ed25519 key deterministically derives an LXMF destination (via standard Ed25519→Curve25519 conversion, or HKDF if that is not exposed). A bridge holding a node's keypair is the authoritative LXMF endpoint for that node; remote bridges can verify the correspondence cryptographically.

Destination naming:

```
Application:  "meshcore"
Aspects:      "node"     — individual node destinations
              "bridge"   — bridge manifest queries
              "channel"  — channel group messaging (destination derived from channel secret)
```

---

## RF Flood Mitigation

This section exists because flood amplification is the single most cited concrete harm in the community record (Discussion #1736, Discussion #2093, and the entire Meshtastic MQTT experience).

### Hard Separation of RF and Bridge Contacts

**Remote contacts never appear on the local LoRa RF medium.** Full stop. The bridge maintains remote contacts in software and delivers them to the companion app over the companion protocol. The local radio is never asked to advertise a remote node, and it never hears remote advertisements at the RF layer.

This is the correct architectural boundary: the local mesh optimises for proximity and spectrum efficiency; wide-area contacts belong at the bridge layer. The two layers should not bleed into each other.

### One Advertisement Per Bridge

A bridge registers as a single gateway contact on the local LoRa mesh. The advertisement carries:

- Display name (e.g., `[GW-WA6]`)
- Standard contact type (`REPEATER`, or a future `BRIDGE` type if added upstream)
- A custom-var field with the bridge's LXMF destination hash

One advert per bridge, regardless of how many nodes are reachable through it. Local firmware-only nodes address the bridge as a relay; the bridge handles the LXMF leg.

### Pull-Based Discovery via Contact Manifests

Bridges publish **contact manifests** as LXMF resources at a `meshcore.bridge` destination. A manifest is a signed, paginated list:

```
Manifest entry:
  public_key    [32 bytes]
  display_name  [up to 32 bytes]
  lat, lon      [microdegrees — subject to precision reduction, see below]
  last_seen     [Unix timestamp]
  region_tag    [short string, e.g. "WA6", "UK-LON"]
  opt_in_flags  [1 byte: position_shared, telemetry_shared, etc.]
```

The companion app requests manifests on demand. Nothing is pushed onto the local mesh. Users filter by region tag, see remote contacts with a visual bridge indicator, and retain clear mental separation between local and remote reachability.

This is the MeshCore analogue of APRS-IS: the backbone carries inter-region data; the RF medium carries only locally-originated traffic.

### Hop-Count Enforcement at Bridge Ingress

Any message arriving at the bridge from a WAN adapter has its effective LoRa hop limit set to zero before it is handed to the local radio. A bridged message is delivered to exactly the recipient node — it is not re-flooded. This mirrors the Meshtastic public-broker policy that was adopted after flood amplification incidents.

### Region Scoping

Each bridge declares a region tag and propagation scope:

| Scope | Behaviour |
|---|---|
| `local` | Bridge does not export local contacts to WAN (private network) |
| `region` | Bridge interoperates only with bridges sharing the same region tag |
| `global` | Bridge interoperates with any connected bridge |

**The default is `region`.** A user who installs a bridge without reading documentation will not accidentally expose their local mesh globally.

---

## Position and PII Handling

The August 2024 Meshtastic MQTT event was triggered by location data, not messages. Over half of bridged traffic was position packets, and third-party mesh-map sites were storing and time-tracking node movements from what users believed to be "regional" channels. This section responds directly.

**Defaults:**

- Position data is **opt-in** per node, not a default-on field of the advertisement forwarded across bridges.
- When opt-in, position precision is **reduced by default** (e.g., to 2–3 km quantisation for publicly bridged manifests, with full precision available only to explicitly authorised recipients via direct LXMF delivery).
- Historical position data is not aggregated or republished by bridges.
- Bridge operators publish a **privacy notice** alongside their manifests stating retention, precision, and sharing policy.

**UX disclosure:**

- Companion apps connected to a bridge should clearly indicate when position sharing is enabled for bridging.
- Remote contacts in the manifest display their position quantisation level — users see "~3 km precision" rather than a false pinpoint.

The principle: the user's first interaction with the bridge should make the privacy implications visible. Safe defaults matter more than buried documentation.

---

## Protocol Coverage

| MeshCore feature | Bridge behaviour |
|---|---|
| Direct message (text and signed) | Delivered via LXMF; signature preserved end-to-end |
| Channel message | Delivered to bridges subscribed to the same channel secret; channel index mapped per region |
| ACK | Synthesised from LXMF delivery receipts |
| Node advertisement | Not propagated to RF; available via manifest query |
| Position | Included in manifest only if node opted in; precision-reduced by default |
| Telemetry (LPP) | Forwarded on explicit request; response routed back |
| Path discovery | Answered locally for remote nodes with maximum path-length marker |
| Neighbour query | Remote nodes appear as synthetic entries with bridge-path indicator |
| Contact sharing | Bridges may exchange contact URIs on request |
| Admin login, raw RF, ACL, radio config | **Not bridged.** These are local-radio concerns and must not traverse WANs. |

---

## Amateur Radio Deployments (Optional Configuration)

Most MeshCore deployments run on license-free ISM bands and have no licensing, identification, content, or encryption constraints beyond ordinary ISM rules. **This section does not apply to those deployments.** It exists for the subset of operators who hold amateur radio licenses and choose to run MeshCore at higher power under amateur radio rules on allocations that overlap ISM (principally the 33 cm band, 902–928 MHz, in ITU Region 2, where portions of the band are simultaneously available as ISM and as amateur radio).

When an operator transmits under an amateur license, amateur radio regulations govern — not ISM rules. The constraints are real and vary by country; operators are responsible for their own compliance. This section outlines the US Part 97 situation (the most-discussed case) and flags where other jurisdictions differ.

### The Reticulum-Encryption Problem

Reticulum encrypts all inter-node traffic by design, and its maintainer has declined to make this optional ([Reticulum Discussion #399](https://github.com/markqvist/Reticulum/discussions/399), locked). US FCC §97.113(a)(4) prohibits messages "encoded for the purpose of obscuring their meaning." Taken together, these facts mean **native Reticulum transport over ham RF is not a clean fit in the US**.

**The proposal's answer: Reticulum and LXMF terminate at the bridge; they do not transit ham RF.**

- The bridge's LXMF core runs on non-ham transports (Internet, HAMNET IP, wired backhaul, licensed ISM).
- On the RF side, the local radio uses standard MeshCore ham-mode channels (unencrypted, with callsign identification per §97.119).
- The bridge, operating as a licensed station under automatic or remote control, is the point at which the transport transitions from encrypted (Reticulum) to in-the-clear (MeshCore ham channel) — and vice versa.

This design pattern is legal in the US, consistent with longstanding internet-linked-repeater practice, and avoids the "Reticulum on ham RF" question entirely.

### Bridge Operator Responsibilities (US Part 97)

A bridge operator whose gateway radio transmits on ham bands is the **control operator** for everything that radio transmits, including relayed traffic. Obligations:

- **§97.119 station identification** every 10 minutes and at end of transmission. In MeshCore ham-mode this is typically satisfied by callsign in the long name plus a periodic identification frame.
- **§97.113(a)(3)** no business communications. Bridges must not relay commercial traffic to ham RF.
- **§97.115 third-party traffic.** Messages from non-licensed persons may be relayed domestically in the US; international third-party relay is permitted only to countries with US third-party agreements (ARRL maintains the list). The architecture supports filtering by destination jurisdiction; operators are responsible for configuring it.
- **§97.109 / §97.213 automatic control.** Gateway operation is automatic control. Deploy only on bands where automatic control is permitted, and provide a documented remote shutdown path.
- **Content auditability.** The bridge logs all relayed traffic (timestamps, source/destination hashes, message size — not necessarily message bodies) for retrospective accountability.

### Jurisdictional Notes

Part 97 is US-specific. Ham-legal deployments elsewhere require separate analysis:

- **UK (Ofcom):** encryption restrictions similar to US; identification by callsign; automatic operation under NoV.
- **CEPT / most of EU:** varies by member state; several allow encryption under specific conditions.
- **Australia (ACMA):** similar in spirit to Part 97; check LCD for current rules.
- **Canada (ISED), Japan, etc.:** each has its own rules; consult local regulator.

The proposal does not attempt to be a legal reference. It simply commits to keeping ham-relevant defaults (no encryption on RF, callsign-based identification, region tagging) available and easy to configure.

### Signed But Not Encrypted

Authentication is permitted under Part 97; encryption for obscuring content is not. LXMF messages carry cryptographic signatures that are verifiable without obscuring content. A bridge operating in ham-legal mode can, in principle, relay the message body in the clear with the LXMF signature attached as metadata, satisfying both the integrity requirement and the non-obscuring requirement. This is worth documenting as a defensible pattern.

---

## Addressing Common Concerns

The following concerns have been raised explicitly in the existing RFCs, discussion threads, and community channels. Each is stated in the form most likely to appear in discussion; responses are specific.

### "Internet bridging breaks the local trust model — the LAX↔SEA incident proves it."

Correct, and this is the governing precedent. The response is structural: **advertisements do not cross bridges by default.** The LAX↔SEA incident occurred because advertisements were forwarded, polluting local neighbour tables. This proposal treats that outcome as unacceptable and makes the corresponding architectural commitment: this is a messaging bridge, not a discovery bridge. Discovery across regions is pull-based and explicit. See the Flood Mitigation section.

### "Internet bridging defeats the whole point of off-grid mesh."

The mesh works when the bridge is down. Bridging is an *additive* capability for users who want wide-area reach; it does not change how the local mesh operates or what it depends on. Local MeshCore users who never interact with a bridge see no change. Operators running an off-grid mesh should not run a bridge; the architecture does not require it.

### "Bridged traffic will flood the RF side — we watched Meshtastic live through this."

Two specific guardrails: (1) no advert propagation, (2) zero hop-count ingress. A message arriving at the bridge from a WAN adapter is delivered to exactly the addressed recipient on LoRa — never re-flooded. This matches or exceeds the Meshtastic public-broker policy adopted after their own flooding incidents.

### "Position data leaked on Meshtastic's public broker — how is this different?"

Three differences: (1) position sharing is opt-in per node, not per channel; (2) position precision is reduced by default in bridged manifests; (3) region scope defaults to `region`, not `global`, so an unconfigured bridge does not join a worldwide broker. The Meshtastic experience is treated as a hard constraint on the design, not a risk to be mitigated with documentation. See the Position and PII section.

### "A centralised Reticulum Transport overlay is just MQTT with extra steps."

Reticulum does not require a single Transport operator; it supports federated, regional Transport nodes, and messages are end-to-end encrypted such that Transport operators cannot read them. This is closer to the federated MQTT broker model (Philly Mesh, Chicagoland, Arizona, etc.) than to a single centralised service. If a Transport operator misbehaves, the result is degraded availability for traffic routed through that operator — not compromised message integrity. Operators dissatisfied with Reticulum can use the MQTT adapter instead; adapter choice is per-bridge.

### "Encryption and Part 97 are incompatible. This proposal's Reticulum dependency is a non-starter for US hams."

Addressed directly in the Amateur Radio section above. Reticulum/LXMF terminate at the bridge; ham RF sees only MeshCore's native in-the-clear mode. This is consistent with longstanding internet-linked-repeater practice.

### "Who operates the backhaul? Who pays? What happens when an operator misbehaves?"

Federated ownership, as in the existing community MQTT brokers. No single entity operates the LXMF interoperability plane; bridges choose which Transport nodes, brokers, or peers they trust. The adapter model means operators can switch transports without re-engineering. End-to-end cryptographic addressing means operators dissatisfied with a Transport peer can route around it.

### "Cross-region advert propagation breaks naming and traceroute UX."

Not addressed as a side effect, addressed as a design principle: adverts do not cross bridges. Naming collisions are prevented by region-tagged manifests. Traceroute answers for remote nodes return a bridge-path indicator rather than a false local hop count. Discussion #2093's existing concerns about advert scaling are orthogonal to this proposal.

### "The MeshCore core team is on record opposing TCP/IP bridging."

Acknowledged. This proposal is designed to be implementable *without* upstream firmware changes — the bridge runs as a companion, not as a firmware-integrated subsystem. If the core team chooses to adopt parts of it natively later, that is welcome; if not, it still functions. The objective is to provide an architectural reference point for the existing bridge projects to converge on, not to mandate upstream changes.

### "Does this obsolete the existing MQTT bridges?"

No. The MQTT adapter (`lxmf-mqtt`) wraps LXMF messages in MQTT payloads using the jmead-style regional topic hierarchy that already exists. MQTT bridges that speak raw MeshCore-over-MQTT continue to work; those that adopt the LXMF-over-MQTT envelope additionally gain interoperability with Reticulum-bridged and Bitchat-bridged nodes. Migration is optional and incremental.

### "Is LXMF overkill for simple local MQTT bridging?"

For a bridge whose only peer is a local MQTT broker and whose users only talk among themselves, yes — LXMF adds overhead with no interop benefit. The adapter model accommodates this: an operator who doesn't need interop can run a raw-MQTT bridge (unchanged from today). The LXMF plane is valuable when multiple transport communities want to reach each other.

---

## Phased Implementation Path

**Phase 1 — Bridge daemon skeleton and contact manifest**

- Companion-proxy pass-through to local radio
- Bridge registers as a single gateway contact on local LoRa mesh
- LXMF core with signed manifest publication
- Remote contacts appear in companion apps with clear indicator

**Phase 2 — Reticulum and MQTT adapters**

- `lxmf-reticulum` adapter over TCP (simplest transport)
- `lxmf-mqtt` adapter using jmead-compatible topic hierarchy
- Direct messaging end-to-end via either adapter

**Phase 3 — Channel messaging, position opt-in, PII handling**

- Channel destination derivation from shared secret
- Position opt-in flags and precision reduction
- Privacy notice publication alongside manifests

**Phase 4 — Additional adapters**

- `lxmf-bitchat` adapter
- `lxmf-tcp` direct peering
- ESP-NOW adapter if demand exists

**Phase 5 — Amateur radio profile**

- Ham-mode configuration preset (no encryption on RF side, callsign identification, automatic control logging)
- Third-party traffic filtering by destination jurisdiction
- Remote shutdown interface for control operators

**Phase 6 — Hardening**

- Store-and-forward refinements (LXMF propagation nodes)
- Loop prevention (seen-message cache, hop-count limits)
- Multi-companion support at bridge layer
- Operator dashboard: traffic stats, manifest audit, rate limits

---

## Invitation to Discuss

This proposal is an architectural sketch, not a mandate. Implementers retain all choices about language, platform, and binding libraries. The goal is to offer a convergence point for the fragmented bridging work already happening, without displacing what works today.

Specific questions where community input is most useful:

- **Is LXMF the right interop envelope,** or is there a lighter-weight format that would serve the same role? (The alternative would be a MeshCore-native bridge-packet format carried inside each transport's native envelope.)
- **Is the pull-based manifest model sufficient for discovery,** or are there use cases that require push semantics (e.g., emergency nets where contacts must become visible without user action)?
- **What are the operational realities of running a bridge** that commenters have experience with but are not yet documented here? MQTT bridge operators in particular have learned lessons (hosting cost, moderation, abuse handling) that this proposal does not yet reflect.
- **How should the companion protocol be extended** to expose manifest queries and bridge configuration to companion apps? Is there a path that does not break existing apps?
- **Has anyone deployed a Reticulum-MeshCore bridge in a ham radio context?** If so, what regulatory posture did you adopt, and what would you change?
- **Where does this proposal conflict with plans the MeshCore core team is already pursuing,** and how can it be adjusted to complement rather than compete?

Critique of the architecture — especially in places where prior experience contradicts it — is the most valuable form of feedback.

---

## References

- [MeshCore Discussion #1736 — Reticulum as Decentralized Backhaul](https://github.com/meshcore-dev/MeshCore/discussions/1736)
- [MeshCore Discussion #2093 — flooded adverts](https://github.com/meshcore-dev/MeshCore/discussions/2093)
- [Meshtastic Discussion #460 — Reticulum vs MQTT](https://github.com/orgs/meshtastic/discussions/460)
- [Meshtastic Discussion #47 — Routing Etiquette](https://github.com/orgs/meshtastic/discussions/47)
- [Meshtastic Public MQTT Broker Changes, Aug 2024](https://meshtastic.org/blog/recent-public-mqtt-broker-changes/)
- [Reticulum Discussion #399 — Part 97 and encryption](https://github.com/markqvist/Reticulum/discussions/399)
- [jmead/Meshcore-Repeater-MQTT-Gateway](https://github.com/jmead/Meshcore-Repeater-MQTT-Gateway)
- [ipnet-mesh/meshcore-mqtt](https://github.com/ipnet-mesh/meshcore-mqtt)
- [73mesh MQTT bridge tutorial](https://www.73mesh.com/2025/11/12/mqttServer.html)
- [Juraj Bednar — Bitchat↔MeshCore bridge](https://juraj.bednar.io/en/blog-en/2026/01/18/bridging-bitchat-and-meshcore-resilient-communication-when-you-need-it-most/)
- [Hoosier Mesh ham radio guidance](https://hoosiermesh.org/docs/reference/ham-radio/)
- [Reticulum](https://reticulum.network) / [LXMF](https://github.com/markqvist/LXMF)
