# CoreNet — FAQ

Short answers to concerns the community has raised about MeshCore wide-area bridging. Each entry links to the corresponding section of the full proposal.

---

**Q: Internet bridging breaks the local trust model — the LAX↔SEA incident proves it. How is this different?**

Advertisements do not cross bridges by default. The LAX↔SEA incident happened because adverts were forwarded, polluting local neighbour tables. This proposal treats that outcome as the governing precedent: CoreNet is a *messaging* bridge, not a *discovery* bridge. Discovery across regions is pull-based and explicit. See [RF Flood Mitigation](README.md#rf-flood-mitigation).

---

**Q: Internet bridging defeats the whole point of off-grid mesh.**

The mesh works when the bridge is down. Bridging is an additive capability for operators who want wide-area reach; it does not change how the local mesh operates or what it depends on. Operators running an off-grid mesh should not run a bridge; the architecture does not require it.

---

**Q: Bridged traffic will flood the RF side — we watched Meshtastic live through this.**

Two structural guardrails: no advert propagation, and zero hop-count ingress. A message arriving at the bridge from a WAN adapter is delivered to exactly the addressed recipient on LoRa — never re-flooded. This matches or exceeds the Meshtastic public-broker policy adopted after their flooding incidents. See [RF Flood Mitigation](README.md#rf-flood-mitigation).

---

**Q: Position data leaked on Meshtastic's public broker in 2024 — how is this different?**

Three differences: position sharing is opt-in per node (not per channel); position precision is reduced by default in bridged manifests; region scope defaults to `region`, not `global`, so an unconfigured bridge does not join a worldwide broker. See [Position and PII Handling](README.md#position-and-pii-handling).

---

**Q: A centralised Reticulum Transport overlay is just MQTT with extra steps.**

Reticulum does not require a single Transport operator; it supports federated, regional Transport nodes, and messages are end-to-end encrypted such that Transport operators cannot read them. Operators dissatisfied with Reticulum can use the MQTT adapter instead — adapter choice is per-bridge.

---

**Q: Encryption and Part 97 are incompatible. Reticulum is a non-starter for US hams.**

Reticulum and LXMF terminate at the bridge; they do not transit ham RF. On the RF side, the local radio uses standard MeshCore ham-mode channels (unencrypted, with callsign identification). This is consistent with longstanding internet-linked-repeater practice. See [Amateur Radio Deployments](README.md#amateur-radio-deployments-optional-configuration).

---

**Q: Who operates the backhaul? Who pays? What happens when an operator misbehaves?**

Federated ownership, as in the existing community MQTT brokers. No single entity operates the LXMF interoperability plane. End-to-end cryptographic addressing means operators dissatisfied with a Transport peer can route around it without compromising message integrity.

---

**Q: Cross-region advert propagation breaks naming and traceroute UX.**

Adverts do not cross bridges — this is stated as a design principle, not a side-effect. Naming collisions are prevented by region-tagged manifests. Traceroute answers for remote nodes return a bridge-path indicator rather than a false local hop count.

---

**Q: The MeshCore core team is on record opposing TCP/IP bridging.**

Acknowledged. This proposal is designed to be implementable without upstream firmware changes — the bridge runs as a companion, not as a firmware-integrated subsystem. If the core team chooses to adopt parts of it natively later, that is welcome; if not, it still functions.

---

**Q: Does this obsolete the existing MQTT bridges?**

No. The MQTT adapter wraps LXMF messages in MQTT payloads using the jmead-style regional topic hierarchy that already exists. MQTT bridges that speak raw MeshCore-over-MQTT continue to work; those that adopt the LXMF-over-MQTT envelope additionally gain interoperability with Reticulum-bridged and Bitchat-bridged nodes. Migration is optional and incremental.

---

**Q: Is LXMF overkill for simple local MQTT bridging?**

For a bridge whose only peer is a local MQTT broker and whose users only talk among themselves, yes. The adapter model accommodates this: an operator who doesn't need interop can run a raw-MQTT bridge, unchanged from today. The LXMF plane is valuable when multiple transport communities want to reach each other.

---

For the architectural detail behind any of these answers, see the full proposal in [README.md](README.md).
