# Security Note 003: Flood Amplification and the LAX↔SEA Precedent

*First published: 2026-04-19 · Revision v0.1 · Status: open to correction*

*Part of the [CoreNet Security Notes](README.md) series.*

---

## Abstract

In the community record around [MeshCore Discussion #1736][1736] —
"Reticulum Network Stack as Decentralized Backhaul" — contributors
described a failure mode in which two independent MeshCore meshes, one in
the Los Angeles area and one in the Seattle area, became inadvertently
joined over an IP-layer transport. The result was that node
advertisements from each mesh flooded into the other, polluting neighbor
tables and consuming airtime on RF resources that had been sized for each
mesh's local population alone. This note examines the structural
mechanism, separates it from superficially similar failures (the
Meshtastic 2024 MQTT incident, Note 001), and draws out the principles
that inform CoreNet's zero-hop ingress rule and the architectural
insistence that "this is a messaging bridge, not a discovery bridge."

[1736]: https://github.com/meshcore-dev/MeshCore/discussions/1736

---

## Context

MeshCore is a flood-routed mesh. When a node wants to send a packet to a
contact for which it has no established path, it floods the packet: the
packet is broadcast, every receiving node checks whether it has seen the
packet's identifier before, and if not, re-transmits it with the hop count
decremented. The flood terminates when hop count reaches zero or when
every node in range has already seen the packet.

Node advertisements are a specific class of flooded packet. They announce
a node's public key, display name, location, and path metadata so that
other nodes can build a contact table and establish paths. Advertisements
are essential to discovery, but they also consume airtime — every
advertisement every node emits is heard, processed, and re-transmitted by
every other node within flood range.

The cost of flood routing is therefore approximately quadratic in the
number of participating nodes: each of N nodes emits advertisements heard
by approximately N-1 others, and each of those re-transmits. The RF
airtime budget of a mesh is finite. Real deployments cope with this by
limiting advertisement rates, tuning hop counts, and — crucially —
constraining the size of any individual mesh to what its airtime budget
can absorb.

A bridge that connects two independent meshes over a transport other than
RF (an IP link, an MQTT broker, a Reticulum Transport path) changes the
membership calculation. If the bridge forwards every packet it receives
from one mesh into the other, the effective N of each local mesh becomes
the sum of both populations. The quadratic cost scales accordingly.

---

## What the community described

The specifics recorded in Discussion #1736 — as this note reconstructs
them from the RFC's summary and the discussion's public visibility — are
that two regionally-distinct MeshCore deployments, one centred on Los
Angeles and one on Seattle, found themselves joined by a transport path
that was not intended as a permanent routing connection. The mechanism of
the joining is less important than the result: advertisements from each
mesh propagated into the other, and the operators of each mesh observed
effects consistent with the flood amplification described above.

Visible symptoms reported in that category of incident include:

- Contact tables populated by large numbers of unfamiliar, distant nodes
- Increased RF airtime utilisation, approaching or exceeding the
  deployment's planned capacity
- Degraded local-mesh routing performance, including delayed or failed
  path establishment to local contacts
- User confusion about which contacts are locally reachable versus
  physically unreachable but present in the contact list

The LAX↔SEA case crystallised in the community record as a specific
reference point — "don't do this, for reasons" — because the effects were
severe enough to be memorable and the cause was structural rather than
implementation-specific.

---

## The precise failure mode

The failure mode is distinct from Note 001's. The Meshtastic 2024 case
was a disclosure failure: encrypted content was readable by parties who
held a universally-distributed key, and the composition of defaults made
the disclosure happen by accident. The LAX↔SEA case is an **amplification
failure**: no content leaked (RF traffic remained encrypted as always),
but the amount of traffic each mesh was asked to carry ballooned.

Several structural properties contributed:

### 1. Flood routing assumes bounded membership

MeshCore's flood algorithm is sound; it is correct-by-construction for any
given set of nodes. What it cannot compensate for is a sudden, unbounded
expansion of that set. The algorithm has no feedback mechanism that says
"we have too many nodes; apply backpressure." Airtime becomes saturated,
collisions increase, effective throughput falls, and local mesh operation
degrades — not because any single component misbehaved but because the
collective load exceeds the physical medium's carrying capacity.

### 2. Advertisements and messages are in the same traffic class

In MeshCore as in most flood-routed meshes, advertisements flow through
the same forwarding path as messages. A bridge that "forwards traffic"
doesn't distinguish by default. Forwarding messages between two meshes
may be a deliberate user feature; forwarding advertisements between them
imports one mesh's discovery population into the other, and that is
rarely what the operator intended.

### 3. Invisible membership change

From an individual node's perspective in either LAX or SEA, nothing about
the local RF environment changed at the protocol layer. The node is still
operating as it always did. What changed was the effective population of
the network it participates in, which only becomes visible through
second-order effects — airtime saturation, unfamiliar contact-table
entries, routing degradation. This is the same "invisible-to-users
membership change" pattern as Note 001, applied to routing rather than
disclosure.

### 4. Symmetry turns a one-way mistake into two-way damage

A unidirectional bridge (A forwards everything it sees to B; B forwards
nothing back) is already enough to impose amplification cost on B. A
bidirectional bridge imposes it on both sides. Most naïve bridging
approaches are bidirectional by default, often for reasons unrelated to
the amplification question ("symmetric bridges are simpler to reason
about"). The symmetry cost is frequently not noticed until the meshes are
large enough for it to hurt.

### 5. Well-intended architectural proposals can contain the same failure

Discussion #1736 was a proposal to use Reticulum as a backhaul for
MeshCore. The proposal was offered in good faith as a way to extend
connectivity, not as a recipe for the LAX↔SEA failure. But a
naïve implementation — one that forwards all traffic including adverts
through the Reticulum transport between meshes — would reproduce the
failure. The distinction between "useful backhaul" and "harmful
backhaul" lives in what is forwarded, not in whether the transport is
used at all. This is the insight that drove the community response.

---

## The community response

Rather than rejecting backhaul bridging, the discussion converged on a
set of architectural principles:

- **Advertisements do not cross bridges by default.** Whatever else is
  bridged, discovery traffic is not propagated across transports without
  explicit opt-in, and even then only in forms that don't multiply load
  on the receiving mesh.
- **Bridges are messaging bridges, not discovery bridges.** The
  distinction is the governing constraint: bridging enables users to
  reach remote peers they already know about; it does not automatically
  populate anyone's contact table with remote nodes.
- **Discovery is pull-based.** If a user wants to see what's reachable
  beyond the local mesh, they query; the query returns results; no traffic
  is pushed onto anyone's RF by virtue of that query alone.
- **Hop count is enforced at ingress.** A message arriving at a bridge
  from a wide-area transport is delivered to exactly its addressed
  recipient on local RF, not re-flooded.

These principles, drawn from the discussion's evolution, are what
CoreNet's spec encodes.

---

## Generalised principles

**P1. Flood routing is membership-bounded by nature.** Any architecture
built on flood routing assumes, implicitly, that the participating
population fits in the available airtime budget. Coupling previously-
independent floods magnifies the population without changing the budget.

**P2. Classify the traffic before you bridge it.** Message traffic and
discovery traffic have very different cost profiles when bridged.
Bridging designs that do not separate the two will at best incur
unnecessary cost and at worst make the mesh unusable. CoreNet's §11.1
(zero-hop ingress) and §13 (transport rules) are specific instances of
this principle.

**P3. Assume bridges will be misconfigured.** Even well-documented
bridging can be set up wrong. The failure modes should be visible when
they happen (diagnostic output, contact-table annotations, airtime
reporting) so operators can recognise and correct them, and they should
be bounded in damage (hop-count enforcement, scope limits) so that a
misconfiguration does not destroy the participating mesh.

**P4. Architecture is not neutral about scale.** A bridging design that
works correctly for 10 nodes on each side may fail at 100 nodes; a design
that works at 100 may fail at 1000. The architecture should state
explicitly what scale it is designed for, and its failure modes should
degrade gracefully as that scale is exceeded.

**P5. Symmetric default, asymmetric policy.** Bridging defaults should
be symmetric in capability (either side can forward) but asymmetric in
policy (each side decides independently what it will accept, forward,
and display). A bridge operator should never be able to unilaterally
import load into a mesh whose operators have not consented to receive it.

---

## Implications for CoreNet

The LAX↔SEA precedent is named in the CoreNet RFC and spec multiple
times. Specific provisions that reflect its lessons:

| Principle | CoreNet provision |
|---|---|
| P1 — Flood is membership-bounded | Zero-hop ingress rule (§11.1): remote adverts never reach local RF. Effective flood population stays bounded to the local mesh. |
| P2 — Classify before bridging | Spec §13 and §11 explicitly distinguish message traffic (forwardable) from advertisement traffic (not forwarded to RF). |
| P3 — Assume misconfiguration | Identity conflict transparency (§10) and publication-state visibility (§8.6) are instances of making bridge behaviour observable to participants. |
| P4 — Architecture states its scale | v0.1 is explicitly designed for two-bridge and small-federation use cases. Larger-scale behaviour is flagged for future revisions, not claimed. |
| P5 — Symmetric default, asymmetric policy | Each bridge's peer list and channel-forwarding configuration are operator-local decisions (§8.2). No remote bridge can impose forwarding on another. |

The single strongest instance is §11.1: the zero-hop ingress rule is not
a mitigation, not a best-effort, not a configurable option. It is a
structural prohibition. CoreNet bridges do not forward remote advertisements
onto local RF, period. Any message from the wide-area transport arrives
at a single known local recipient and is delivered directly, with hop
count set to zero before the radio is asked to transmit.

This is the architectural commitment that makes the LAX↔SEA failure
structurally impossible under CoreNet, not merely unlikely.

---

## Relationship to other notes

- **Note 001** (shared-secret broadcast) is about *disclosure* of content
  that users expected to be private. Note 003 is about *capacity* of
  routing infrastructure that users expected to be sized for their local
  membership. Both involve invisible membership change across a bridge,
  but the failure modes are orthogonal.
- **Note 002** (bridge operator trust) is relevant because the bridge
  operator's configuration choices directly determine whether the LAX↔SEA
  failure can happen. A trustworthy bridge is one that configures itself
  per the CoreNet zero-hop ingress rule, regardless of what its operator
  could in principle enable.
- **Future Note 010** (traffic analysis in encrypted meshes) will touch
  on the observation that increased traffic volume, even when content is
  encrypted, itself constitutes a disclosure — a flood-amplified mesh
  reveals its amplification to anyone listening to its RF.

---

## Uncertainties and open questions

This note relies more heavily on secondhand reconstruction than Notes 001
and 002, because the discussion thread itself is the primary source and
the specific reported symptoms are scattered through community
conversations rather than consolidated in a single authoritative post.
Areas where firsthand correction is particularly welcome:

- **The specific mechanism** by which LAX and SEA meshes were joined. The
  reconstruction here treats it as "an IP-layer transport path" without
  specifying whether it was MQTT, Reticulum, a direct TCP tunnel, or
  another mechanism. The mechanism may matter for the fine-grained
  lesson.
- **The magnitude** of the airtime impact observed. Words like "severe"
  and "noticeable" appear in the community record, but quantitative
  reports — percent saturation, dropped packet counts, effective
  throughput figures — would strengthen the note.
- **The duration and resolution** of the incident. How long did the
  flooding persist? Was the bridge manually disconnected, did a timeout
  resolve it, or did configuration updates fix the problem? The
  remediation path is historically instructive.
- **Whether the affected operators published retrospectives** beyond the
  linked discussion. Links to such accounts would improve the citation
  trail.

Readers with direct involvement in either affected deployment, or in the
surrounding community discussion, are encouraged to supply corrections
and additional context via the CoreNet issue tracker.

---

## References

- **MeshCore, Discussion #1736** — Reticulum Network Stack as
  Decentralized Backhaul. The primary community record of the LAX↔SEA
  case and the architectural discussion it produced.
  https://github.com/meshcore-dev/MeshCore/discussions/1736
- **MeshCore, Discussion #2093** — Flooded adverts. A related
  discussion examining advert scaling pressures under normal
  operation (not specifically the LAX↔SEA case).
  https://github.com/meshcore-dev/MeshCore/discussions/2093
- **CoreNet Protocol Specification v0.1, §11.1** — Zero-hop ingress
  rule. The structural expression of this note's lessons.
  [`/corenet-spec-v0.1.md`](../corenet-spec-v0.1.md)
- **CoreNet Security Note 001** — Shared-secret broadcast. Companion
  note on a differently-shaped failure of the same general class
  (invisible membership change across a bridge).
  [`001-shared-secret-broadcast-meshtastic-2024.md`](001-shared-secret-broadcast-meshtastic-2024.md)
- **CoreNet Security Note 002** — Bridge operator trust. Companion
  note on what bridges can and cannot see; §11.1 context.
  [`002-bridge-operator-trust.md`](002-bridge-operator-trust.md)

---

## Revision history

- **v0.1 (2026-04-19)** — initial publication. Open to correction,
  particularly on the specifics of the LAX↔SEA mechanism, magnitude, and
  resolution, which are reconstructed from the CoreNet RFC's summary and
  the public visibility of Discussion #1736 rather than from direct
  firsthand reporting.
