# Security Note 001: Shared-Secret Broadcast and the Meshtastic 2024 MQTT Incident

*First published: 2026-04-19 · Revision v0.1 · Status: open to correction*

*Part of the [CoreNet Security Notes](README.md) series.*

---

## Abstract

In August 2024 the Meshtastic project restructured its public MQTT broker
after recognising that location data from publicly-keyed default channels
was being aggregated by third-party websites. The incident is often
summarised as "MQTT bridges leaked data because they didn't encrypt," but
that framing misses what actually went wrong: the encryption worked as
designed. The structural failures lay in membership scaling, default
behaviours, and the composition of two independently-reasonable features —
default channels and MQTT uplink — into an outcome neither had been
designed to produce. This note walks through what happened, why, and how
those lessons shape CoreNet's architecture.

---

## Context

Meshtastic, like MeshCore, uses **shared-secret channels** as its primary
group-communication primitive. A channel is a `(name, pre-shared key)` pair;
anyone holding the PSK can encrypt, decrypt, send, and receive on that
channel. There is no intra-channel hierarchy: membership is set-theoretic,
not role-based.

Meshtastic firmware ships with a built-in channel commonly called
**LongFast** (or previously **Default**), intended to give new nodes a
common frequency-equivalent on which to discover each other out of the box.
The LongFast PSK is hard-coded in the firmware and therefore effectively
public knowledge — anyone with a Meshtastic device has it, and the key is
widely documented online.

Meshtastic also supports **MQTT uplink and downlink** per channel. An
operator can configure any given channel to mirror its traffic to an MQTT
broker (uplink) and/or to receive traffic from one (downlink). The
Meshtastic project has historically operated a **public MQTT broker**
(`mqtt.meshtastic.org`) where anyone may connect to exchange bridged
traffic.

The combination that produced the incident:

1. LongFast had a public PSK.
2. LongFast was the default channel on new devices.
3. MQTT uplink was a simple per-channel toggle, often enabled to "get on
   the network" or to appear on community maps.
4. The public broker accepted any connection.

None of these was, in isolation, obviously dangerous. Their composition was.

---

## What happened

Any internet-connected party could:

1. Connect to `mqtt.meshtastic.org`.
2. Subscribe to a wildcard topic covering uplinked traffic.
3. Receive every message any participating node had uplinked globally.
4. Decrypt any LongFast traffic using the universally-known LongFast PSK.

And because Meshtastic nodes beacon their GPS position at intervals on
their local mesh — with the position packet typically carried on the same
default channel — **a large fraction of uplinked traffic was encrypted
position data decryptable by anyone on the broker.**

Third-party websites took the obvious next step: subscribe to the public
broker, decrypt position packets, aggregate them into live maps. Some
retained history. The result, when operators became aware of it, was that
individual node positions — including movements over time — were visible
to anyone who cared to look, and to anyone scraping those websites for
their own purposes.

Users who had enabled uplink expecting **"my fellow local operators can
see I'm online"** discovered they had enabled **"my GPS position is
broadcast to a global audience that includes anyone, with resolution
fine enough to identify my house."**

The Meshtastic project's response — detailed in their [August 2024 blog
post][blog] — restructured the public broker to forward less by default,
changed uplink defaults, removed position from default-channel forwarding,
added UI warnings when enabling uplink, and promoted the pattern of using
separate private channels for meaningful traffic.

[blog]: https://meshtastic.org/blog/recent-public-mqtt-broker-changes/

---

## The precise failure mode

The common summary "MQTT bridges leaked data because they didn't encrypt"
is technically incorrect in an instructive way. **The encryption worked.**
LongFast packets were encrypted under the LongFast PSK before transmission
and decrypted on receipt. The broker forwarded ciphertext faithfully.
Third parties decrypted using the same PSK every device ships with.

The failures were structural. In order of decreasing proximity to the
incident itself:

### 1. A "channel" with universal membership is not a channel; it's a broadcast

Treating the LongFast PSK as a key produces a category error in users'
mental models. A key implies a bounded set of holders; if the set is
effectively unbounded, the traffic is effectively plaintext.

### 2. Default configurations were composed in ways no single default implied

LongFast-as-default was reasonable. Per-channel MQTT uplink was reasonable.
A public broker was reasonable. Each was defensible on its own. The
combination — default channel, uplinked by default pattern, broker open to
anyone — produced an outcome that no individual default decision would
have produced, and that no single feature's documentation warned against.

### 3. Position precision was full GPS resolution

Even if LongFast membership had been smaller, beaconing position to
within-meters precision made every beacon a more consequential datum than
it needed to be. Precision reduction would have substantially reduced
impact even under the same disclosure surface.

### 4. Bridging changed the membership model invisibly to users

The user's local experience was unchanged: same radio, same channel, same
fellow operators visible on the console. The fact that enabling uplink had
turned the channel into a global publication was not surfaced at the rate
required for informed consent. Users who did not read documentation
carefully — which is most users — could not reasonably have understood
what they were enabling.

### 5. Scraping sites operated without institutional responsibility

The public broker was run by the Meshtastic project. The scraping sites
were volunteer efforts run by third parties. No single entity had the
authority to impose norms on data aggregation, and the architecture
implicitly assumed goodwill from actors it had no mechanism to constrain.

---

## What Meshtastic changed

The [August 2024 blog post][blog] is the authoritative source; in summary:

- **Default-channel traffic is no longer uplinked to the public broker by
  default.** Users must opt in explicitly per channel if they want forwarding.
- **Position packets on default channels are no longer forwarded** from the
  public broker.
- **The uplink UI includes warnings** about the public-disclosure
  implications of enabling forwarding.
- **Private-channel patterns are promoted** as the recommended configuration
  for any communication the operator cares about.
- **Position precision defaults were revisited** in several places.

The changes broke some existing deployments. Users who had been relying on
the prior behaviour (particularly for map visibility) had to reconfigure.
The Meshtastic project absorbed the cost of a real public correction to
restore the privacy posture users had implicitly expected.

Readers interested in the post-incident discussion are directed to
Meshtastic's [Routing Etiquette discussion][discussion47] and the blog
post.

[discussion47]: https://github.com/orgs/meshtastic/discussions/47

---

## Generalised lessons

Five principles, in increasing generality:

### L1. Cryptographic privacy scales inversely with membership

A secret shared between two parties protects well. A secret shared among a
million parties protects nothing. Shared-secret channels are suitable for
bounded groups with disciplined key distribution; they are unsuitable for
groups whose membership is effectively open. The failure mode when this
invariant breaks is silent, because the encryption continues to operate
normally — only its guarantees are empty.

### L2. Bridging amplifies membership

Local RF membership is naturally bounded by range. Bridging to an
internet-reachable transport — MQTT, Reticulum, anything else — makes
effective membership potentially unbounded, without the user's local
experience changing at all. The mental model "people I can hear" no longer
corresponds to "people who can hear me."

### L3. Metadata leakage is frequently worse than content leakage

Even if content were unreadable, knowing **who** is online, **where**,
**when**, and **how often** is often the more sensitive datum. Position,
timing, and activity pattern are first-order leaks in their own right.
Systems that encrypt content without disciplining metadata exposure may
still produce the outcome users were trying to avoid.

### L4. Safe defaults are mandatory, because users do not read

If the default workflow produces a problematic outcome, most users will
experience that outcome. The existence of a better configuration somewhere
in the documentation does not rescue users from the default path. Designs
must be safe for users who click through first-run screens without reading.

### L5. Operational responsibility cannot be assumed; it must be anchored

Architectures that depend on third parties to behave well, without any
institutional mechanism to enforce norms, are architectures without
enforcement. Good will is not a protocol. Systems that bridge across trust
domains should either accept that their data will be used by the most
adversarial plausible actor, or contain the scope of what they expose.

---

## Implications for CoreNet

Every principle above maps to specific choices in the current CoreNet
specification. The spec was written with this incident as background, so
these aren't parallel rediscoveries; they are deliberately borrowed lessons.

| Principle | CoreNet provision |
|---|---|
| L1 — Privacy scales with membership | Channel publication state is controlled by channel members via in-channel `::corenet publish::` messages (§8.4), never by bridge operators unilaterally. Publication authority is coextensive with channel membership. |
| L2 — Bridging amplifies membership | Zero-hop ingress rule (§11.1): remote advertisements never reach local RF. Remote contact visibility requires explicit pull (`who` query, §7.1) or explicit member opt-in for channels (§7.4). |
| L3 — Metadata leakage | Control-channel posts reference channels by hash only, never by name (§6.4, §8.1). Requester identities are never included in control-channel posts (§11.4). Attribution rules differ between in-channel (OK, members already trust each other) and control-channel (not OK, broader audience). |
| L4 — Safe defaults | Channels default to *unpublished* (§8.4, §11.5). Position precision reduction is on by default (§11.3, ~1km resolution). Opt-in is affirmative, member-initiated, and visible to all channel members via bridge-posted notices (§8.6). |
| L5 — Operational responsibility | CoreNet is a federation protocol, not a registry (§4.3). Each federating relationship is a bilateral operator decision. There is no public broker analogue. Identity conflicts and anomalies are published on a per-federation control channel with opt-in participation, so surveillance is at least visible to participants. |

The alignment is not coincidence. CoreNet's RFC names the Meshtastic 2024
incident as a governing constraint on the design, and each of these
provisions exists in the specific form it does because of lessons from
that event and from the related MeshCore Discussion #1736 LAX↔SEA
cross-continental advert leakage report.

---

## Uncertainties and open questions

Claims in this note that rest on secondhand community memory rather than
primary sources, flagged for future correction:

- Specific percentages of bridged traffic that were position packets
- Specific third-party website operators and their retention practices
- The precise chronology of when scraping was first publicly noted
  versus when the project responded
- The identities of the individuals who first raised the concern

Readers with firsthand knowledge — especially current or former
contributors to the Meshtastic project, or operators of affected bridges —
are encouraged to submit corrections via the CoreNet issue tracker.

---

## References

- Meshtastic project, "Recent Public MQTT Broker Changes," August 2024.
  https://meshtastic.org/blog/recent-public-mqtt-broker-changes/
- Meshtastic, Discussion #47 — Routing Etiquette.
  https://github.com/orgs/meshtastic/discussions/47
- Meshtastic MQTT documentation.
  https://meshtastic.org/docs/configuration/module/mqtt/
- MeshCore, Discussion #1736 — Reticulum Network Stack as Decentralized
  Backhaul (the LAX↔SEA cross-continental advert leakage precedent).
  https://github.com/meshcore-dev/MeshCore/discussions/1736
- MeshCore, Discussion #2093 — Flooded adverts.
  https://github.com/meshcore-dev/MeshCore/discussions/2093
- CoreNet Protocol Specification v0.1.
  [`/corenet-spec-v0.1.md`](../corenet-spec-v0.1.md)

---

## Revision history

- **v0.1 (2026-04-19)** — initial publication. Open to correction.
