# CoreNet: Safe Bridging for MeshCore

*A routing and addressing layer that connects MeshCore regions without the side-effects that have plagued prior bridging efforts.*

*Author: Art Botterell, KD6O — see [ABOUT.md](ABOUT.md).*

---

**Revision 0.2, April 2026.** This is a revised proposal, updated in response to community discussion of the [original December 2025 edition](archive/README-2025-12.md). CoreNet develops through open conversation; further revisions will continue to reflect community thought. A summary of what changed in this revision appears at the end of this document.

**Companion documents:**

- [`corenet-spec-v0.1.md`](corenet-spec-v0.1.md) — the normative protocol specification
- [`meshcore-lxmf-encoding.md`](meshcore-lxmf-encoding.md) — reference message encoding table
- [`security-notes/`](security-notes/) — reference notes on security-relevant incidents and design choices
- [`bridge/`](bridge/) and [`tests/`](tests/) — Python reference implementation sketch

---

## What CoreNet is, in one paragraph

CoreNet is a thin layer that sits between a local MeshCore mesh and whatever wide-area transport its operator chooses — Reticulum, MQTT, plain TCP, Bitchat, future alternatives. It gives users a way to address remote peers (`@KD6O@SEA hello`), to see who's reachable (`who`), and to bridge channels between zones, all without changing MeshCore firmware or any existing client, and without leaking remote advertisements onto the local RF. The value proposition is not interop for interop's sake; it is inter-zone reach *with* the flood-discipline, privacy defaults, and transparency that earlier bridging efforts have often lacked.

## What CoreNet is not

- **Not a replacement for existing bridges.** jmead's MQTT gateway, ipnet-mesh, Juraj Bednar's Bitchat bridge, and others all continue to work unchanged. CoreNet is positioned above them as a convergence layer for operators who want its particular discipline.
- **Not a modification to MeshCore.** No firmware changes, no client changes. Stock MeshCore users interact with CoreNet routers as ordinary contacts on their local RF mesh.
- **Not a centralized service or registry.** No authority issues router names, allocates regions, or arbitrates disputes. Collisions and conflicts resolve locally or socially, as they do in amateur radio and grassroots mesh culture.
- **Not a transport.** LXMF over Reticulum is the reference v0.1 transport, but CoreNet's addressing, discipline, and transparency rules apply over any wire.

## Motivation

MeshCore provides reliable, low-power LoRa mesh communication within a region. Its bounded range is a feature, not a limitation: a dense local mesh is resilient, self-contained, and independent of external infrastructure.

Operators in different regions, or groups separated by terrain or distance, currently cannot reach each other, and the existing bridging work has fragmented along transport lines. Each bridge today is a point-to-point translation: a node bridged to MQTT cannot reach a node bridged to Bitchat without a second custom adapter. Worse, several well-documented incidents have shown what happens when bridging is done naïvely — most cited being the LAX↔SEA cross-continental advert leakage (MeshCore Discussion #1736) and the August 2024 Meshtastic MQTT incident, where third-party map sites harvested location data from "regional" channels users thought were local.

CoreNet is an attempt to describe the bridging problem and solve it once, so individual transport adapters don't each have to figure it out.

## Prior Art

This proposal is not a greenfield design. The following projects and discussions have shaped the problem space; readers are encouraged to review them.

### Existing MeshCore bridging projects

- **[jmead/Meshcore-Repeater-MQTT-Gateway](https://github.com/jmead/Meshcore-Repeater-MQTT-Gateway)** — ESP32 firmware acting as both MeshCore repeater and MQTT bridge. Introduced the hierarchical regional topic namespace (`MESHCORE/AU/NSW`) as the de-facto MQTT pattern.
- **[ipnet-mesh/meshcore-mqtt](https://github.com/ipnet-mesh/meshcore-mqtt)** — host-side Python bridge over serial/BLE/TCP.
- **[73mesh.com MQTT bridge tutorial](https://www.73mesh.com/2025/11/12/mqttServer.html)** — Pi-plus-LoRa-node DIY pattern.
- **Juraj Bednar's [Bitchat↔MeshCore bridge](https://juraj.bednar.io/en/blog-en/2026/01/18/bridging-bitchat-and-meshcore-resilient-communication-when-you-need-it-most/)** — cross-protocol bridge firmware.
- **MeshCore native Bridge primitives** — the firmware already supports ESP-NOW and RS-232 bridges. New transports (MQTT, Reticulum, Bitchat) extend this pre-existing abstraction.

### Relevant discussions and RFCs

- **[MeshCore Discussion #1736 — Reticulum as Decentralized Backhaul](https://github.com/meshcore-dev/MeshCore/discussions/1736)** — notes the concrete harm of two meshes (LAX, SEA) getting inadvertently joined over IP with cross-continental advert leakage. CoreNet treats that incident as governing precedent.
- **[Meshtastic Discussion #460 — Reticulum vs MQTT](https://github.com/orgs/meshtastic/discussions/460)**.
- **[MeshCore Discussion #2093 — flooded adverts](https://github.com/meshcore-dev/MeshCore/discussions/2093)** — existing scaling pain that bridging must not worsen.
- **[Meshtastic Public MQTT Broker Changes, Aug 2024](https://meshtastic.org/blog/recent-public-mqtt-broker-changes/)** — the cautionary tale every bridging proposal must answer.

---

## Guiding principles

1. **The local RF medium is sacred.** No WAN-originated traffic appears on LoRa by default. Bridged contacts live at the application layer only.
2. **Local-first is a cultural commitment.** The mesh works when the backhaul fails. Bridging is additive, not foundational.
3. **Advertisements do not cross bridges.** Discovery across regions is pull-based and explicit. The LAX↔SEA incident is treated as settled precedent.
4. **Identity is cryptographic, not administrative.** Router identity derives from public keys. Names are labels; hashes are truth.
5. **Safe by default.** Users do not read manuals. Privacy defaults, precision reduction, and scope limits must be safe out of the box.
6. **Transparent conflict handling.** Identity collisions and state changes are publicly signaled on a dedicated control channel. Silent failure is the worst failure mode.
7. **ISM-first, amateur-radio-friendly.** CoreNet assumes ISM-band deployments by default. Amateur radio operation is an optional, explicitly-configured profile with its own constraints.
8. **No upstream firmware or client changes required.** Bridges operate as companions. Stock MeshCore works as-is.

---

## How it works

CoreNet v0.1 adds four mechanisms to a stock MeshCore environment. Each is summarized below; the [specification](corenet-spec-v0.1.md) defines their normative behavior.

### Addressing: `@callsign@region`

A user on one zone addresses a peer in another zone by prefixing a direct message to a router with a CoreNet address:

```
→ @KD6O@SEA hey, how's the weather up there
```

The router parses the prefix, routes the message via its wide-area transport to the peer's home router, which delivers it to the local user as a DM from itself, marked with the origin:

```
← [@W5XYZ@LAX] hey, how's the weather up there
```

No client changes are needed. Users learn the convention — it's familiar from Twitter and Slack — and use it on whatever MeshCore client they already have.

### Roster and channel discovery

Users can query a router to learn what's reachable:

```
→ who
← 3 nodes visible via bridge:
    @KD6O@SEA   (3m)   [a1b2c3d4]
    @W7ABC@PDX  (12m)  [e5f6g7h8]
    @N2XYZ@SAC  (1h)   [i9j0k1l2]

→ channels
← 2 public channels at bridge.lax.example.net:
    corenet-wa       (bridged to 3 regions)
    emergency-coord  (bridged to 6 regions)
```

Pull-based by default: nothing is pushed onto local RF, nothing is spammed anywhere. Bracketed fingerprints let users verify identities out-of-band if they care to.

### Channel bridging, nailed-up or ad-hoc

A router can bridge a MeshCore channel across zones. Channels can be:

- **Nailed-up** by the operator in configuration (persistent cross-zone interop for well-known channels)
- **Ad-hoc** activated by user DM command (temporary activation, e.g., for emergencies or scheduled nets, with automatic expiration)

```
→ bridge corenet-wa 30m
← Bridging #corenet-wa enabled, expires 16:00 UTC.
```

Channel secrets never leave the local context; only encrypted channel traffic crosses the bridge. Loop prevention (seen-tag discipline) ensures messages don't ping-pong between bridges.

### Publication state, controlled by channel members

Each bridged channel has a publication state — *public* or *unpublished* — that determines whether the router lists it by name in `channels` query responses. The default is unpublished.

Any channel member can change the state by posting a control message in the channel:

```
::corenet publish::
::corenet unpublish::
```

The mechanism is cryptographically grounded: only members holding the channel secret can post valid control messages. No bridge operator can unilaterally publicize a channel; no registry or central authority can either. Bridges post human-readable notices in the channel when state changes, so no one is surprised:

```
← [CoreNet] #corenet-wa is now publicly discoverable across the federation.
            Posted by @KD6O at 15:42 UTC. Any member may revert with
            ::corenet unpublish::
```

This inherits MeshCore's flat channel trust model: the people you trust with the channel secret are also the people authorized to act on its publication state. The spec's security considerations note this plainly rather than pretend otherwise.

---

## The control channel

CoreNet defines a well-known control channel, `corenet-ctl`, for federation-wide signaling. Any federation of cooperating routers shares the secret among participants; the name is public, but participation is opt-in. Routers post signed messages for:

- Router online announcements
- Roster summaries (by count; no names of non-opted-in nodes; no requester identities)
- Bridge activation/expiration notices (by channel **hash**, never by name)
- Identity conflict reports (see below)

Channel names never appear on `corenet-ctl`. The plane is transparent about *what is happening* (federation activity, conflicts, anomalies) while withholding *what it is about* (channel names, user identities) from non-members.

### Identity conflict transparency

Router identity is a cryptographic hash of its public keys — globally unique by construction. If a router ever observes two peers announcing the same hash with different public keys (indicating key theft, misconfiguration, or the astronomically improbable accidental collision), it retains the incumbent, refuses the latecomer, and posts a signed report to `corenet-ctl`:

```
[CoreNet] Identity conflict at bridge.lax.example.net:
  hash a1b2c3d4 —
    pubkey fp e5f6g7h8 (seen 14:23:15Z via bridge.sac.alice.net) [retained]
    pubkey fp 9a0b1c2d (seen 15:47:02Z via bridge.sac.bob.net) [refused]
```

This turns a silent, near-undiagnosable failure into public information that affected operators can see, verify, and coordinate to resolve. The precedent is certificate transparency: making conflicts visible is more effective than trying to prevent or silently resolve them.

---

## Architecture

CoreNet is transport-agnostic:

```
┌──────────── Zone A ─────────────┐    ┌──────────── Zone B ─────────────┐
│                                 │    │                                 │
│    Stock clients (any)          │    │    Stock clients (any)          │
│           │                     │    │           │                     │
│     companion protocol          │    │     companion protocol          │
│           │                     │    │           │                     │
│     [CoreNet router]            │    │     [CoreNet router]            │
│     • addressing                │    │                                 │
│     • routing                   │    │                                 │
│     • discipline                │    │                                 │
│           │                     │    │           │                     │
└───────────┼─────────────────────┘    └───────────┼─────────────────────┘
            │                                      │
    ╔═══════╧══════════════════════════════════════╧═══════╗
    ║   Wide-area transport (operator's choice):           ║
    ║   • Reticulum/LXMF (v0.1 reference)                  ║
    ║   • MQTT                                             ║
    ║   • Direct TCP                                       ║
    ║   • Bitchat                                          ║
    ║   • any future adapter                               ║
    ╚══════════════════════════════════════════════════════╝
```

The router owns addressing, routing decisions, loop prevention, opt-in policy, and control-plane discipline. The wire transport carries signed, typed messages between routers.

### The v0.1 reference transport: LXMF over Reticulum

LXMF provides authenticated, encrypted, store-and-forward-capable messaging over Reticulum's transport-agnostic network stack. Its properties — cryptographic addressing, signed metadata, resilience across transport combinations — fit CoreNet's requirements cleanly, and its reference libraries are mature. The [encoding table](meshcore-lxmf-encoding.md) specifies which MeshCore message types map to which LXMF fields.

Operators preferring MQTT, direct TCP, or other transports can implement alternative adapters that preserve CoreNet's addressing and discipline rules (specification Section 13). Cross-transport gateways are straightforward because all transports carry the same typed message set.

### Reference implementation status

A Python reference implementation is developing alongside the specification. The [`bridge/`](bridge/) directory contains the frame codec, encoding layer, and routing decision logic. The [`tests/`](tests/) directory exercises these with mock transports — 77 passing tests covering frame framing, encoding correctness, routing decisions, and a two-bridge in-process end-to-end pipe. The code is not yet connected to real Reticulum or real MeshCore hardware; that's the next increment.

---

## ISM and amateur radio

Most MeshCore deployments run on license-free ISM bands (868 MHz Europe, 915 MHz Americas) and have no licensing, identification, content, or encryption constraints beyond ordinary ISM rules. **CoreNet's defaults are ISM defaults.**

Some licensed operators run MeshCore at higher power under amateur radio rules on amateur allocations that overlap ISM (notably 33 cm in ITU Region 2). Those deployments carry additional constraints that are the operator's responsibility. CoreNet accommodates them as an optional configuration:

- **Encryption on the wide-area transport, not on the RF.** The router's wide-area link (Reticulum, whatever) may be encrypted; the local MeshCore RF is unencrypted as always. The bridge is the transition point. This pattern matches longstanding internet-linked-repeater practice in US §97 and is compatible with most jurisdictions.
- **Station identification by callsign.** A router operating in amateur mode uses its operator's callsign as its short tag; MeshCore ham-mode station identification (§97.119 in the US) is satisfied by the local radio as it already is.
- **Automatic control.** Gateway operation is automatic control; deploy only on bands and modes where this is permitted. Provide a documented remote-shutdown path.
- **Third-party traffic.** §97.115 permits domestic third-party relay; international third-party relay requires a bilateral agreement. The routing table supports filtering by destination jurisdiction; operators are responsible for configuring it.
- **Content auditability.** The router logs relayed traffic (timestamps, source/destination hashes, sizes) for retrospective accountability.

Part 97 is US-specific. Ham-legal deployments elsewhere require separate analysis; CoreNet does not attempt to be a legal reference.

---

## Addressing common concerns

Most of the questions below have been raised in the community record. Responses reflect where the current design has landed.

### Cross-region advert leakage

The classic concern, concretely raised in MeshCore Discussion #1736 around a LAX/SEA incident: whether internet bridging inevitably propagates local advertisements across regions, polluting neighbor tables and producing the kind of cross-continental mess the community wants to avoid.

The architectural response is the zero-hop ingress rule: advertisements do not cross bridges, and remote contacts never appear on the local RF. This is not mitigation, it is structural prohibition. The LAX/SEA outcome is treated as an unacceptable failure mode that the design must prevent by construction.

### RF flooding

A closely related worry: bridged traffic arriving in a new region could be re-flooded onto local RF and amplify airtime consumption.

Two guardrails: (1) no advert propagation, (2) zero hop-count at bridge ingress. A message arriving from a wide-area transport is delivered to exactly the addressed recipient on RF — never re-flooded. This matches or exceeds the Meshtastic public-broker policy adopted after their 2024 incidents.

### Position data and privacy

The August 2024 Meshtastic MQTT incident — in which third-party map sites harvested location data from channels users believed to be regional — is the other cautionary precedent every bridging proposal must answer.

Three relevant differences in the present design: (1) position sharing is opt-in per node, not per channel; (2) position precision is reduced by default in bridged manifests; (3) channel publication is opt-in and member-controlled rather than operator-controlled. The Meshtastic experience is treated as a hard design constraint, not a documentation problem.

### Coexistence with existing MQTT bridges

Operators of existing MQTT bridges may reasonably ask whether CoreNet is meant to replace what they have built.

It is not. MQTT bridges that speak their own raw MeshCore-over-MQTT dialect continue to work unchanged. A CoreNet router can sit *in front of* an MQTT link — it translates `@callsign@region` addressing and roster queries into MQTT topic operations, adding an addressing and discipline layer without replacing the underlying wire. Operators who already run MQTT and are happy with it can adopt CoreNet's benefits without changing their broker, their topic hierarchy, or their operational playbook.

### US Part 97 and encryption

US amateur radio regulations prohibit transmissions "encoded for the purpose of obscuring their meaning," which has led to reasonable skepticism about any proposal involving encrypted transports alongside ham RF.

The wide-area transport's encryption terminates at the router, before the RF. Ham RF carries only MeshCore's native in-the-clear mode. This matches longstanding internet-linked-repeater practice. LXMF's signature mechanism — authentication without obscuring content — is permitted under §97.113; authentication and content-encryption are distinct operations under the regulations.

### MeshCore core-team positions on TCP/IP bridging

Members of the MeshCore development community have previously expressed reservations about TCP/IP bridging in general, and any bridging proposal needs to engage with those reservations rather than work around them.

CoreNet is designed to operate *without* upstream firmware changes — the router is a companion, not a firmware subsystem. If the core team chooses to adopt any part of this natively later, that is welcome; if not, it still functions. The objective is a convergence point for existing bridge projects, not a mandate.

### Who operates the wide-area infrastructure

A reasonable question about any bridging proposal: who runs the infrastructure, and what recourse exists when an operator behaves badly?

Federated, as in the existing MQTT community. No single entity operates CoreNet's wide-area plane; routers choose which peers they federate with. End-to-end cryptographic addressing means operators dissatisfied with a peer can route around. Control-channel transparency makes misbehavior visible. The model matches what the grassroots mesh community already practices.

### Channel publication authority

Because any channel member can change publication state, users may reasonably worry about a rogue member publicizing a sensitive channel against the wishes of others.

The mechanism inherits MeshCore's flat channel trust model: whoever has the channel secret is a peer. If you would not trust someone to *read* the channel, you should not share the secret with them — publishing the name is a strictly smaller capability than reading all content. Disputes among members are visible (bridges post notices in the channel when state changes) and resolvable by sending the opposite message. A future specification revision may address sub-member governance for deployments that need it.

### Naming, registries, and authority

Some readers have asked whether CoreNet is attempting to establish DNS-like naming or a central registry for mesh networks.

It is not. CoreNet has no registry, no authority, and no uniqueness guarantees at any naming level. Names are labels; cryptographic hashes are identity. Collisions are resolved locally by each federating router with public reporting of conflicts, the way federated email and XMPP handle similar issues. The specification is explicit: *CoreNet is a federation protocol, not a registry.*

---

## Roadmap

**v0.1** — the present document and specification. Channel bridging, addressing, roster and channels queries, control channel with conflict transparency, publication state. LXMF/Reticulum as reference transport. Reference implementation sketch in Python.

**v0.2 (open questions tracked in spec Appendix A)** — manifest wire format with signatures; peer-of-peer trust rules; MQTT adapter and gateways between transports; refined notice-suppression coordination; publication governance mechanisms (for deployments wanting a sub-member authority model).

**v0.3 and beyond** — further transports (Bitchat, ESP-NOW); CoreNet-aware client extensions (transparent remote DM threading, automatic roster refresh, etc.); operator tooling; propagation-node topology recommendations; possibly upstream firmware integration if the MeshCore team chooses.

The line between v0.1 and v0.2 is drawn at *demonstrably-useful-now*. v0.1 can run between two operators today with existing MeshCore clients, existing radios, existing transports. Later versions add richness without removing that foundation.

---

## Invitation to participate

This proposal is an architectural sketch, not a mandate. Implementers retain all choices about language, platform, and binding libraries. The goal is a convergence point for the fragmented bridging work already happening, without displacing what works today.

Questions where community input is most useful:

- **Is the addressing convention (`@callsign@region`) the right shape**, or is there a more natural syntax that still works with stock clients?
- **Does the control-channel transparency model fit the culture**, or is it too noisy / too visible / not visible enough for the deployments people have in mind?
- **Do the publication-state mechanics (in-channel control messages, any-member authority) match operators' expectations**, or is a governance model needed earlier than v0.2?
- **How should transport gateways work** between a CoreNet-native LXMF router and an existing MQTT-native bridge? What's the minimum viable bridging between transports?
- **Has anyone deployed something similar** and what would you do differently?
- **Where does this conflict with plans the MeshCore core team is pursuing**, and how can it be adjusted to complement rather than compete?

Critique — especially where prior experience contradicts the current design — is the most valuable form of feedback. CoreNet has improved substantially between revisions because of concrete pushback on specific mechanisms; that is the norm this project wants to reinforce.

Discussion happens in this repository's **[GitHub Discussions](https://github.com/artbotterell/CoreNet/discussions)** and **[Issues](https://github.com/artbotterell/CoreNet/issues)**. Conversation is kept in the open so others can learn from it.

---

## Changes in this revision

Compared to the December 2025 original:

- **Reframed from "LXMF as an interoperability plane" to "routing and addressing layer with safety discipline."** LXMF/Reticulum is now described as the reference v0.1 transport rather than the proposal's central idea. Alternative transports are first-class.
- **Added explicit addressing convention** (`@callsign@region`) usable from stock clients without modification.
- **Added explicit discovery mechanisms** (`who` and `channels` queries) with privacy-preserving defaults.
- **Added the `corenet-ctl` control channel** as a transparency plane for federation activity, with signed posts, hash-only channel references, and published conflict reports.
- **Replaced bridge-operator-controlled channel announcements with member-controlled publication state**, using in-channel control messages. Any channel member can publish or unpublish; bridges post human-readable notices when state changes.
- **Refined namespace handling** — named collisions are resolved locally with public reporting, not centrally; cryptographic hashes are the authoritative identifier, names are labels at every level.
- **Narrowed v0.1 scope** to what works with stock clients and existing infrastructure today. Richer client integrations and automatic transparent remote DM threading are deferred to later versions.
- **Companion protocol specification** ([`corenet-spec-v0.1.md`](corenet-spec-v0.1.md)) introduced as a separate normative document.

---

## References

- [MeshCore Discussion #1736 — Reticulum as Decentralized Backhaul](https://github.com/meshcore-dev/MeshCore/discussions/1736)
- [MeshCore Discussion #2093 — flooded adverts](https://github.com/meshcore-dev/MeshCore/discussions/2093)
- [Meshtastic Discussion #460 — Reticulum vs MQTT](https://github.com/orgs/meshtastic/discussions/460)
- [Meshtastic Public MQTT Broker Changes, Aug 2024](https://meshtastic.org/blog/recent-public-mqtt-broker-changes/)
- [Reticulum Discussion #399 — Part 97 and encryption](https://github.com/markqvist/Reticulum/discussions/399)
- [jmead/Meshcore-Repeater-MQTT-Gateway](https://github.com/jmead/Meshcore-Repeater-MQTT-Gateway)
- [ipnet-mesh/meshcore-mqtt](https://github.com/ipnet-mesh/meshcore-mqtt)
- [73mesh MQTT bridge tutorial](https://www.73mesh.com/2025/11/12/mqttServer.html)
- [Juraj Bednar — Bitchat↔MeshCore bridge](https://juraj.bednar.io/en/blog-en/2026/01/18/bridging-bitchat-and-meshcore-resilient-communication-when-you-need-it-most/)
- [Reticulum](https://reticulum.network) / [LXMF](https://github.com/markqvist/LXMF)
- [MeshCore](https://meshcore.co.uk/)
