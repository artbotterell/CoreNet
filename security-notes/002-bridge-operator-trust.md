# Security Note 002: Bridge Operator Trust — What End-to-End Encryption Protects and What It Doesn't

*First published: 2026-04-19 · Revision v0.1 · Status: open to correction*

*Part of the [CoreNet Security Notes](README.md) series.*

---

## Abstract

"End-to-end encrypted" is a property between a specific pair of endpoints
at a specific protocol layer. Different layers of the same system can have
different endpoints, and a bridge may be transparent to one layer while
being an endpoint at another. This note works through what a bridge
operator actually sees in three common configurations — pure relay, CoreNet
routing gateway, and cross-transport gateway — and separates the claims
that hold up from the ones that are often repeated without qualification.
The practical upshot is neither the reassuring "nobody can read anything"
nor the alarming "your bridge operator sees everything"; it is that
visibility is layered, deliberate, and knowable, and operators who
understand the layering can deploy and document trust models honestly.

---

## Context

Mesh-networking discussions frequently treat "end-to-end encryption" as a
binary property: either a system has it (in which case all third parties,
bridges included, are opaque to the content) or it doesn't (in which case
anyone in the middle sees everything). Real systems do not obey that
binary. A given message typically passes through multiple protocol layers,
each with its own notion of who the endpoints are. The message may be
encrypted end-to-end at one layer and transparent at another, and a bridge
may be a non-endpoint at the outer layer while being a fully-participating
endpoint at an inner one.

This note is primarily about MeshCore and CoreNet, with MQTT and Reticulum
as specific cases, but the framework applies to any layered messaging
system with relays and gateways.

---

## Three kinds of "end-to-end"

Before working through cases, it helps to name the distinctions that
"end-to-end" collapses:

**Transport-layer encryption.** Protects the link between a client and its
immediate peer. TLS is the canonical example. It prevents eavesdroppers on
the wire from reading content, but the peer sees plaintext. An MQTT
connection over TLS is encrypted from client to broker; the broker reads
everything.

**Content encryption at an intermediate layer.** A payload is encrypted
before being handed to a lower transport, and decrypted after being
received from one. Both layers may independently have their own encryption.
Meshtastic and MeshCore DMs are encrypted at the mesh-application layer
before being handed to LoRa. When the same packet is later forwarded over
MQTT, the MQTT layer sees ciphertext, not because MQTT encrypts but because
what MQTT is carrying was already ciphertext.

**End-to-end at the semantic layer.** Only the sender and the intended
recipient can read the content. This is what users usually mean when they
say "end-to-end encrypted." It's a property of the combination of
encryption primitives, identity binding, and key distribution — not just
one algorithm.

A bridge can be transparent at (a), (b), or (c), or an endpoint at any of
them, independently. Saying "this bridge is end-to-end encrypted" without
specifying which layer and which endpoints is a category error.

---

## Case A: Pure pass-through relay

The simplest case. A MeshCore DM from user X to user Y is encrypted at the
mesh-application layer using X's private key and Y's public key. The
resulting ciphertext travels over LoRa as an opaque payload. A bridge to
MQTT takes that ciphertext, wraps it in an MQTT publish, and sends it over
TLS to a broker. The broker forwards it to the other side's bridge. The
downstream bridge unwraps the MQTT envelope and sends the mesh-application
ciphertext onto local LoRa.

**What the bridge operators see:**

- The fact that a message exists, and its size
- The source and destination mesh-application identifiers (typically
  pubkey prefixes or truncated hashes)
- Timestamps
- MeshCore framing metadata
- *Not* the message content

**What the MQTT broker sees:**

- Same as bridge operators, plus the MQTT topic the message was published
  on (which can itself leak context if the topic scheme encodes structure)
- Routing metadata for MQTT's own forwarding logic
- *Not* the message content

This is the pattern existing MeshCore MQTT bridges use, and it preserves
end-to-end encryption at the semantic layer (between X and Y) despite the
bridge being a full participant at the transport layer. It's a real and
useful property, and it's what ham-radio operators familiar with
internet-linked repeaters would recognise: the repeater forwards what it
hears, but doesn't comprehend it.

Channel messages work the same way when the bridge does not hold the
channel secret: ciphertext goes through unmodified.

## Case B: CoreNet routing gateway

A user sends a DM addressed to a remote peer using CoreNet's addressing
convention: `@KD6O@SEA hello there`. The DM is encrypted at the
mesh-application layer to the *bridge's* public key (because the DM is
being sent to the bridge, which will route onward). The bridge receives
the ciphertext, decrypts it (because it is the mesh-layer recipient),
parses the `@KD6O@SEA` prefix, looks up SEA's router, and re-encrypts the
body for transmission via LXMF to that router.

**What this bridge operator sees:**

- All of Case A's metadata
- The plaintext of the message body
- The source (originating user's pubkey) and target (`@KD6O@SEA`) of the
  CoreNet-level address
- The routing decision made

This is fundamentally different from Case A. The CoreNet routing bridge
is a **semantic-layer endpoint**, not just a transport relay. It has
access to plaintext during the moment between decryption of the inbound
envelope and encryption of the outbound one. No amount of cryptographic
sophistication in the transports hides this; it is a necessary property of
a router that needs to parse an address from the payload to decide where
to route.

This is the same trust model as a cross-band amateur radio repeater: the
repeater hears what passes through on one band and retransmits on another,
and the repeater's control operator is responsible for what the repeater
emits. The repeater operator can, in principle, listen to traffic. The
institutional norm is that they generally don't, and the FCC holds them
accountable for what their station does. CoreNet bridges inherit this
model; the CoreNet specification does not attempt to cryptographically
prevent operators from seeing what they are routing, because it would not
be possible to do so.

## Case C: Cross-transport gateway

A bridge that terminates one transport and re-originates traffic on a
different transport — say, LXMF on Reticulum inbound and MQTT outbound —
is necessarily a plaintext midpoint. The two transports have incompatible
encryption models (Reticulum's automatic Curve25519 to destination
identities; MQTT's lack of any built-in content encryption). Whatever
came in encrypted must be decrypted before it can be re-encrypted (or not)
for the outbound transport.

**What this bridge operator sees:**

- Complete plaintext of every message it gateways
- Both sides' identities and addressing metadata
- Timing, size, and correlation information that could enable targeted
  traffic analysis across both transports

This is the most visibility of any of the three cases, and it's an
unavoidable property of cross-transport gateways. The only technical
mitigation is to add a second layer of end-to-end encryption between the
ultimate endpoints (outside the gateway's reach), which is a heavier
engineering lift and requires all participants to cooperate on the outer
envelope. For most realistic mesh-networking deployments, accepting that
the cross-transport gateway is a trust boundary is the practical path.

---

## What bridges see that users may not realise

Across all three cases, even when bridges do not see content, they see a
substantial amount of metadata:

- **Who is talking to whom.** Source and destination hashes are visible at
  every layer that does routing.
- **When.** Timestamps are visible by necessity.
- **How often.** Traffic patterns are visible and often diagnostic.
- **How much.** Message sizes are visible even when content is opaque.
- **Path and topology.** Which route a message took, which bridges it
  passed through, which transports were involved.
- **Presence.** The fact that a participant is online and reachable.

Note 004 (planned) will address metadata-specific risks in more depth. The
short version: for many realistic threat models, metadata leakage is a
larger concern than content leakage, and "end-to-end encryption" in the
strict content sense does not protect against it.

---

## What bridges do not see

Equally worth stating, because the inverse claim is also common:

- **Content of messages they only relay.** In Case A, the content is
  opaque. A bridge that is doing pure pass-through for a well-designed
  protocol genuinely cannot read the messages even in principle.
- **Content of channels whose secret they don't hold.** Ciphertext is
  ciphertext regardless of who is forwarding it.
- **Keys of participants.** Private keys stay on the originating devices;
  the bridge does not receive them.

A bridge operator who honestly describes their own visibility can
credibly say "I forward but cannot read" for Case A traffic, and should
honestly say "I see plaintext" for Case B and C traffic.

---

## The repeater analogy — and its limits

Ham operators will recognise the pattern. An analog voice repeater:

- Hears what passes through it (no encryption); the repeater operator
  could, in principle, monitor
- Is not expected to; norms and regulation anchor trust
- Is held accountable (under §97 in the US) for content the station emits
- Is transparent to participants about its operator and its scope

A CoreNet bridge in Case B or C operates on the same model. The operator
can see plaintext; the operator is trusted (or not) based on community
reputation; the operator is responsible for what the station transmits;
participants who enable such a bridge are implicitly agreeing to that
trust model.

Where the analogy frays: analog voice repeaters produce no persistent
record of traffic. A CoreNet bridge trivially can log every message it
sees. Retention policy is therefore a disclosure the operator owes to
participants, in a way that voice-repeater operators historically did not.

---

## Generalised principles

**P1. Name the endpoints when you claim end-to-end.** "End-to-end
encrypted" without specifying which endpoints at which layer is an
ambiguous claim. Good systems document this precisely; bad systems let
users assume.

**P2. Bridges doing routing are endpoints at some layer.** If a bridge has
to parse addressing information from a payload to decide where to send it,
that bridge is a semantic-layer endpoint for whatever it's parsing. No
cryptographic design hides this.

**P3. Cross-transport gateways are plaintext midpoints.** The only
alternative is an outer-layer end-to-end envelope independent of both
transports, which requires protocol cooperation from all parties.

**P4. Metadata visibility is approximately constant across cases.**
Whether or not a bridge can read content, it can almost always see who is
communicating with whom and when. This is the dominant privacy property
for most threat models.

**P5. Honesty about visibility is a trust-building move.** Operators who
clearly document what their bridges can and cannot see are easier to trust
than operators who imply blanket opacity.

---

## Implications for CoreNet

The CoreNet specification is Case B by design for any traffic that uses
the `@callsign@region` addressing convention, and Case A for traffic that
is passed through opaquely (direct MeshCore DMs not addressed to CoreNet,
channel messages when the bridge does not hold the channel secret).
Specific provisions that reflect this:

| Principle | CoreNet provision |
|---|---|
| P1 — Name the endpoints | The spec's §13 describes the transport model; future revisions should make the Case A/B/C distinction explicit |
| P2 — Routing bridges are endpoints | The `@callsign@region` convention is explicit about the bridge being a sender/recipient at the mesh layer, not a transparent relay |
| P3 — Cross-transport is plaintext | The MQTT adapter design (not yet in spec but discussed in the RFC) treats the gateway as a plaintext midpoint and is honest about this |
| P4 — Metadata visibility | Spec §11.4 and §11.6 restrict what metadata can travel to the control channel — the strongest mitigation CoreNet makes for metadata leakage |
| P5 — Honesty about visibility | The spec's language around "operator trust" in §12.1 is deliberate; this note is one of the disclosure artifacts |

**Gap worth addressing in the spec:** §13 (Transport) currently does not
make the Case A / Case B / Case C distinction explicit. A short subsection
naming the three cases and stating which mode a given CoreNet provision
operates in would clarify the trust model materially. This is a candidate
revision for v0.2.

---

## Disclosure recommendations for bridge operators

Operators running CoreNet bridges should, in their service description:

- State explicitly that the bridge is a semantic-layer endpoint for
  `@callsign@region`-addressed traffic (Case B)
- State what is logged, retained, and for how long
- State who has access to those logs
- State the bridge's update and security-patching practices
- State the jurisdiction in which the bridge operates (relevant for
  subpoena and disclosure obligations)

None of these are protocol requirements, but they are the minimum
threshold for informed participant consent. Without them, users are being
asked to trust without the information to do so knowingly.

---

## Uncertainties and open questions

- Whether any existing CoreNet-adjacent bridge implementations already
  publish operator-visibility disclosures; if so, we should link them as
  positive examples.
- The specific legal posture of bridge operators under various
  jurisdictions' intercept and disclosure laws — deferred to specialist
  analysis; this note does not claim legal expertise.
- Whether the Case B reencryption pattern is sufficient, or whether an
  outer-layer envelope (e.g., client-to-client signed payload that is
  opaque to the routing bridge) would be a desirable future addition to
  CoreNet. This is a v0.2+ design question.

---

## References

- CoreNet Protocol Specification v0.1, §11 (Privacy Requirements) and §12
  (Security Considerations).
  [`/corenet-spec-v0.1.md`](../corenet-spec-v0.1.md)
- CoreNet Security Note 001 — Shared-secret broadcast and the Meshtastic
  2024 MQTT incident.
  [`001-shared-secret-broadcast-meshtastic-2024.md`](001-shared-secret-broadcast-meshtastic-2024.md)
- Reticulum Network Stack documentation — destination and identity model.
  https://reticulum.network/manual/
- LXMF specification.
  https://github.com/markqvist/LXMF
- FCC §97.205 — Repeater station responsibilities (the amateur radio
  analogue for trust models).
  https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97/subpart-D/section-97.205

---

## Revision history

- **v0.1 (2026-04-19)** — initial publication. Open to correction.
