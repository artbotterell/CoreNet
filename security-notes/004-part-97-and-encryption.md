# Security Note 004: Part 97 and Encryption — A Practical Reading for Amateur Deployments

*First published: 2026-04-19 · Revision v0.1 · Status: open to correction*

*Part of the [CoreNet Security Notes](README.md) series.*

---

> **This note is not legal advice.** It describes the current authors'
> reading of the relevant US FCC regulations as they bear on mesh-
> networking deployments, and the architectural patterns that follow
> from that reading. Operators are responsible for their own regulatory
> compliance. When in doubt, consult the ARRL, FCC guidance, or
> qualified counsel.

---

## Abstract

US amateur radio rules prohibit "messages encoded for the purpose of
obscuring their meaning" (47 C.F.R. §97.113(a)(4)). This is commonly
summarised as "Part 97 forbids encryption on ham radio." That summary is
both too narrow and too broad: too narrow because the rule is about
*purpose*, not about any particular cryptographic primitive; too broad
because it collapses several categorically different uses of cryptography
into a single prohibition. This note unpacks what the rule actually says,
separates the uses of cryptography that are clearly permitted from those
that are clearly prohibited, and describes the architectural pattern that
CoreNet and similar projects use to stay cleanly on the permitted side
while still benefiting from modern protocol cryptography on the
non-RF segments of their transport.

---

## The text

47 C.F.R. §97.113(a)(4):

> No amateur station shall transmit:
> …
> (4) Music using a phone emission except as specifically provided
> elsewhere in this section; communications intended to facilitate a
> criminal act; messages encoded for the purpose of obscuring their
> meaning, except as otherwise provided herein;

The relevant clause for our purposes is "**messages encoded for the
purpose of obscuring their meaning**." Three words in that clause carry
most of the weight: **encoded**, **purpose**, and **meaning**.

- **Encoded** is broader than "encrypted." Any encoding counts, in
  principle — digital modes, compression, ciphers. What matters is not
  the presence of encoding but whether the encoding's purpose is the
  prohibited one.
- **Purpose** is the test. The rule does not outlaw encoding per se;
  it outlaws encoding whose purpose is the obscuring. An encoding
  chosen for bandwidth efficiency, error correction, or digital
  transmission standards is not governed by this clause even if a
  human listener cannot read the bits.
- **Meaning** — the semantic content of the message — is what the rule
  protects from obscuring. It does not refer to metadata, identity,
  timing, or other observable properties of the transmission.

The clause also includes "except as otherwise provided herein." Relevant
exceptions elsewhere in Part 97:

- §97.207(f): telecommand of space stations may use codes to obscure
  meaning (to prevent hijacking)
- §97.211: space telecommand and telemetry may use codes
- §97.215: telecommand of model craft may use codes
- §97.201(f) / §97.213(b): control of a station may use codes

These exceptions are narrow and specific. They don't create a general
permission for encryption in amateur service.

---

## What the rule permits

Several uses of cryptography are *not* "encoded for the purpose of
obscuring meaning," and are therefore not prohibited by §97.113(a)(4):

**Digital signatures and authentication.** A signature attached to a
plaintext message cryptographically proves the message came from the
holder of a specific private key. The plaintext is readable by anyone;
the signature does not obscure its meaning. Signatures are widely
accepted as permitted under Part 97 — they are, in substance, a
cryptographic identification mechanism, and §97.119 explicitly requires
station identification.

**Compression.** A compressed message is encoded for efficiency. The
purpose is bandwidth reduction, not obscuring. Digital compression
codecs (Codec 2, Opus, etc.) are widely used under Part 97.

**Error correction.** FEC codes and similar mechanisms encode messages
to survive noise. Their purpose is integrity, not obscurity.

**Checksums, hashes, and message digests.** These encode a message to
verify it; the original message is transmitted separately and the digest
is a check on it. Not obscuring.

**Digital modes in general.** FT8, JS8, Winlink's various modes, and
others encode text and data for robust transmission. They are encoded,
but clearly not for obscuring meaning — they are well-documented open
protocols whose entire point is reliable communication.

**Control passwords and telecommand codes.** Specifically permitted by
§§97.201, 97.213, 97.215, 97.207 for the narrow purposes listed.

**Encryption over non-amateur transports.** If a bridge receives traffic
over the internet (encrypted end-to-end by TLS, Reticulum's native
encryption, or anything else), decrypts it at the bridge, and then
transmits the plaintext content on amateur RF, the amateur RF
transmission is in the clear. The encryption was on the internet leg,
not on the amateur leg. This is the longstanding pattern used by
internet-linked repeaters (IRLP, EchoLink, AllStarLink) and is not
affected by §97.113(a)(4).

---

## What the rule prohibits

The clear cases:

**Content encryption whose purpose is confidentiality.** If you encrypt
a message such that only the intended recipient can read it, and you
transmit that ciphertext on amateur RF, that is "encoding for the
purpose of obscuring meaning." This is the core prohibition.

**Proprietary codecs chosen to exclude third-party listeners.** Using an
undocumented or closed voice codec on amateur RF, in place of the
open digital voice modes that exist, creates at minimum a presumption
that the purpose includes obscuring — especially if the open alternatives
would work.

**Ciphered modes operating as such.** Any mode that presents itself as
"encrypted amateur communication" on amateur RF falls squarely within
the prohibition.

---

## The edge cases where reasonable people disagree

Regulators have not definitively ruled on every scenario operators
might construct. Examples where the community has active, unresolved
discussion:

**Shared-secret "channels" on amateur RF.** MeshCore and Meshtastic both
use per-channel PSKs. If a PSK is widely distributed (the LongFast
pattern discussed in Note 001), a reasonable argument exists that the
encryption isn't *effectively* obscuring meaning because anyone on the
network can decrypt. If a PSK is closely held, the encryption clearly
is obscuring, and operating in that configuration on amateur RF is
problematic. The community broadly settles this by operating ham-mode
deployments with content encryption disabled entirely, relying on
authentication for identity and leaving content in the clear.

**Authentication that incidentally prevents passive reading.** A
protocol whose primary purpose is authentication but whose mechanism
incidentally produces unreadable-by-third-parties output could, in
principle, be challenged. The authors are not aware of any enforcement
action against this use; it seems unlikely, but it is not unambiguous.

**Traffic whose "content" is itself machine-to-machine signalling.**
Telemetry, routing messages, and protocol-internal traffic don't
obviously carry "meaning" in the sense a third-party listener would
interpret. Whether this traffic class is within or outside the scope of
§97.113(a)(4) is not settled by FCC guidance known to the authors.

These cases are flagged for transparency. Operators encountering them
should consult qualified opinion before assuming either result.

---

## ISM versus amateur operation

The MeshCore ecosystem operates primarily on ISM bands (868 MHz in
Europe, 915 MHz in the Americas, etc.) where Part 97 does not apply.
ISM rules (Part 15 in the US) do not prohibit content encryption;
encrypted MeshCore DMs and channel messages are entirely lawful on ISM.

The question becomes relevant only when an operator chooses to run
MeshCore under amateur radio rules — typically at elevated power or on
amateur-allocated spectrum that overlaps ISM (notably the 33 cm band,
902–928 MHz, in ITU Region 2). Operating "as a licensed amateur" means
operating under Part 97, which means §97.113(a)(4) applies.

There is no ambiguity about which rule set governs: it is determined by
the operator's license posture and the power/band configuration, not by
the protocol. An operator choosing to transmit at 10 W under an amateur
license has made the Part 97 choice, regardless of what the firmware
defaults to.

---

## Wide-area transports with built-in encryption

Many modern transport protocols encrypt by default. TLS-wrapped TCP,
WireGuard-tunnelled backhaul, and newer cryptographic networking
stacks (including Reticulum, which underlies LXMF and serves as
CoreNet's v0.1 reference transport) all treat end-to-end encryption
as a structural property rather than a configurable feature.

When a mesh wants to use such a transport for wide-area connectivity,
the Part 97 question becomes: *where does that transport run?* If it
runs over amateur RF, every packet transmitted is, by design, encoded
in a way whose purpose includes obscuring meaning from third parties
who lack the destination's keys — a clean §97.113(a)(4) mismatch. If
it runs over non-amateur transports (the public internet, wireline
backhaul, licensed ISM, or anything else where Part 97 does not
apply), there is no Part 97 issue at all, because no amateur
transmission is taking place on that segment.

The clean answer, and the one CoreNet adopts, is **encryption-heavy
transports stay off amateur RF.** The amateur RF segment carries only
the local mesh's native MeshCore mode with content encryption
disabled. Wide-area connectivity rides on transports where encryption
is permitted.

This is the longstanding pattern of EchoLink, AllStarLink, IRLP, and
other internet-linked repeater systems: the encrypted (or encoded)
segment lives off-air, amateur RF carries cleartext, and the bridge is
the transition point between the two domains. CoreNet adopts the
pattern directly. Its wide-area transport — Reticulum/LXMF in v0.1,
potentially MQTT or other adapters in future revisions — terminates at
the bridge and does not transit amateur RF. The bridge, operating as
the control operator's station, receives cleartext MeshCore traffic
on RF, hands it to the wide-area transport where encryption is
permitted, and delivers inbound traffic as cleartext on RF.

---

## MeshCore's ham-mode pattern

The MeshCore community operates MeshCore under amateur rules by
configuring nodes in a mode that disables content encryption on RF.
Specifically, as the authors understand the current practice:

- DM content is transmitted in the clear (authentication signatures may
  still be present; these are not prohibited)
- Channel messages are transmitted in the clear (the shared-secret
  encryption is disabled)
- Station identification follows §97.119 (callsign at required
  intervals)

This is the configuration CoreNet's spec assumes for ham-mode
deployments. The same firmware runs on ISM with encryption enabled; the
ham-mode difference is a local configuration choice, not a protocol
change.

Operators configuring ham-mode MeshCore should verify:

1. Content encryption is disabled in their firmware configuration
2. Their callsign is correctly set for §97.119 identification
3. They understand §97.115 (third-party communication) if they are
   relaying messages from non-licensed persons
4. They understand §97.201/§97.213 (automatic and remote control) if
   their bridge operates unattended

---

## CoreNet's design implications

CoreNet's architecture is shaped by the reading above:

| Regulatory reading | CoreNet provision |
|---|---|
| Encryption on amateur RF is prohibited | Ham-mode deployments use MeshCore's in-the-clear native mode on RF; CoreNet's wide-area encryption terminates at the bridge, never transits amateur RF |
| Signatures (authentication) are permitted | LXMF signatures and CoreNet's identity system use authentication cryptography that is compatible with amateur operation |
| Control passwords are permitted (§97.201) | CoreNet admin features (if wired up in a future revision) can use authentication/access-control mechanisms without a Part 97 problem |
| Station identification is required (§97.119) | Bridge `router_name` and `short_tag` in ham deployments should incorporate the operator's callsign; CoreNet does not prevent this |
| Third-party traffic (§97.115) | Bridge operators relaying traffic from non-licensed persons domestically are permitted under §97.115; international relay requires bilateral agreement. CoreNet's manifest and routing policies expose the information needed for per-jurisdiction filtering |
| Automatic control (§97.201) | Bridges operate as automatically-controlled stations. Operators must deploy on bands where auto-control is permitted and provide a documented remote-shutdown path. CoreNet's daemon architecture is compatible with this requirement |

The spec's §13.1 and §12.1 language around wide-area transports
terminating at the bridge — encryption off amateur RF, cleartext on —
is the most important architectural commitment this note supports.
Whatever else changes in CoreNet, and whatever wide-area transports
future revisions add, that commitment should remain structural rather
than configurable.

---

## Other jurisdictions

Part 97 is US-specific. The authors' cursory understanding of other
jurisdictions' approach, with major caveats:

- **UK (Ofcom):** restrictions similar in spirit to Part 97. Encryption
  generally not permitted on amateur bands; identification by callsign
  required; automatic operation subject to NoV (Notice of Variation).
- **CEPT / most of EU:** varies substantially by member state. Some
  members permit encryption under specific conditions; others align
  with UK/US.
- **Australia (ACMA):** amateur LCD (Licence Conditions Determination)
  broadly aligns with Part 97's encryption prohibition.
- **Canada (ISED):** similar in spirit to Part 97; refer to RIC-3 and
  the RBR-4 standard.
- **Japan, Brazil, India, etc.:** each has its own rules; consult local
  regulator.

Operators outside the US should not rely on this note for their own
compliance. The structural pattern — keep encryption off amateur RF,
use the bridge as the transition point, sign rather than encrypt where
practical — generalises well but specific rules vary.

---

## Practical guidance

For an operator running CoreNet (or any similar bridge) under amateur
rules in the US:

1. Configure your local MeshCore node in ham mode with content
   encryption disabled. Verify this by inspecting transmitted packets
   if you can.
2. Use your FCC callsign as the basis of your `local_callsign` and
   `router_name` so §97.119 identification is handled by the radio's
   normal advertisement behaviour and your bridge's announcements.
3. Run the bridge's wide-area transport — Reticulum/LXMF, MQTT, or any
   other content-encrypted protocol — on internet, wireline, or
   licensed-ISM connections. Do not configure an encrypted transport
   to operate on amateur frequencies.
4. If your bridge is unattended, deploy only on bands where automatic
   control is permitted; establish and document a remote-shutdown path.
5. If you relay third-party traffic, understand §97.115. Bridges that
   receive messages from non-licensed users domestically are generally
   fine; international relay requires case-by-case analysis.
6. Log your bridge's transmitted traffic at a granularity sufficient
   for retrospective accountability (timestamps, source/destination
   identifiers, sizes), in case a question about your station's
   transmissions ever arises. Logging content is a separate decision
   with separate privacy implications (see Note 002).
7. Consider joining your local ARRL section or regional amateur
   digital-comms group; other operators running internet-linked
   stations have relevant practical experience.

For an operator running CoreNet exclusively on ISM (no amateur radio
involvement), this note does not apply. ISM rules permit content
encryption; CoreNet's default configuration is intended for that
regime.

---

## What this note is not

- **Not legal advice.** The authors are not attorneys. §97.113 has
  been read carefully but regulators, not commentary, determine
  enforcement.
- **Not a defence against enforcement.** If an operator's station is
  the subject of an FCC inquiry, "a GitHub note said this was okay"
  is not a valid response. Operators are responsible for their own
  compliance.
- **Not a complete treatment.** §97 is a substantial body of regulation;
  this note addresses one clause and its immediate vicinity. Operators
  should read §97 in full.
- **Not stable across jurisdictional or regulatory change.** If the
  FCC updates Part 97, or if other regulators change their rules,
  this note's analysis may be outdated. Check the revision date.

---

## Uncertainties and open questions

Claims in this note that would benefit from authoritative confirmation:

- **The ARRL's current position** on specific edge cases (shared-secret
  channels with widely-distributed PSKs, authentication-only protocols,
  machine-to-machine telemetry). The ARRL publishes guidance
  periodically; we should cite authoritative statements when they
  exist.
- **Recent FCC Enforcement Bureau actions**, if any, that bear on
  MeshCore-style or Meshtastic-style operation. The authors are not
  aware of specific enforcement against these protocols but have not
  exhaustively checked.
- **MeshCore's exact "ham mode" configuration details.** The note
  assumes a specific pattern (encryption disabled, callsign
  identification) based on community convention. Firmware authors
  or documented configuration should be cited directly; current
  references may become stale.
- **The specific regulatory posture in jurisdictions not covered
  above.** Contributions from operators in other countries are
  welcome.
- **Whether any license-class-specific nuances apply** (e.g., Technician
  vs. General vs. Extra) to bridge operation. The authors do not
  believe so for the patterns described, but the issue is worth
  confirmation.

Corrections, citations of authoritative sources, and contributions from
operators with direct regulatory-compliance experience are actively
sought.

---

## References

- **47 C.F.R. Part 97** — Amateur Radio Service, full text.
  https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97
- **47 C.F.R. §97.113** — Prohibited transmissions, including the
  encoding-to-obscure clause.
  https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97/subpart-B/section-97.113
- **47 C.F.R. §97.119** — Station identification requirements.
  https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97/subpart-B/section-97.119
- **47 C.F.R. §97.115** — Third-party communications.
  https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97/subpart-B/section-97.115
- **47 C.F.R. §97.201** — Auxiliary stations.
  https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97/subpart-D/section-97.201
- **ARRL** — Amateur Radio Relay League.
  https://www.arrl.org/
- **Reticulum Discussion #399** — Community discussion of Reticulum's
  encryption policy and its implications for amateur operation.
  https://github.com/markqvist/Reticulum/discussions/399
- **CoreNet Protocol Specification v0.1, §13.1 and §12.1** —
  Architectural commitment to Reticulum terminating at the bridge.
  [`/corenet-spec-v0.1.md`](../corenet-spec-v0.1.md)
- **CoreNet Security Note 001** — Shared-secret broadcast and the
  related question of widely-distributed PSK configurations.
  [`001-shared-secret-broadcast-meshtastic-2024.md`](001-shared-secret-broadcast-meshtastic-2024.md)
- **CoreNet Security Note 002** — Bridge operator trust and the
  transition between encryption domains at a bridge.
  [`002-bridge-operator-trust.md`](002-bridge-operator-trust.md)

---

## Revision history

- **v0.1 (2026-04-19)** — initial publication. Open to correction,
  particularly from licensed amateur operators with enforcement-history
  knowledge, from non-US operators on their jurisdictions' rules, and
  from ARRL members with current authoritative guidance.
