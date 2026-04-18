# CoreNet — Abstract

MeshCore deployments are bridged today in multiple incompatible ways: MQTT gateways, Bitchat bridges, Reticulum experiments, ESP-NOW repeaters. A node on one bridge cannot reach a node on a different bridge without a custom adapter for every pair.

Meanwhile, the MeshCore and Meshtastic communities have already learned hard lessons about what goes wrong when bridges are built carelessly — cross-continental advert leakage between regional meshes, location-data harvesting from public brokers, and airtime flood amplification on the RF medium.

This proposal argues for **LXMF — the lightweight extensible message format layered on Reticulum — as a common interoperability envelope**, with lightweight adapters for each wide-area transport. Existing MQTT, Bitchat, and ESP-NOW bridges keep working; bridges that additionally adopt the LXMF envelope gain cross-transport reach without custom gateways for every pair.

The architecture commits structurally to: no advertisement propagation across bridges, zero-hop ingress onto the local RF medium, opt-in position sharing with precision reduction, and region-scoped defaults. Amateur-radio deployments are addressed as an opt-in configuration; most MeshCore use is on license-free ISM bands, and the proposal's default assumptions are ISM assumptions.

This is a draft for community discussion. Prior art is acknowledged; common objections are answered; the architecture is additive, not replacement.

Full proposal: [README.md](README.md) · Author: [ABOUT.md](ABOUT.md)
