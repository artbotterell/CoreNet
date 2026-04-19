# CoreNet Security Notes

A series of short reference documents examining security-relevant incidents,
design choices, and practices in the mesh-networking world, with particular
attention to how they inform — or ought to inform — CoreNet's architecture
and the ecosystem it participates in.

## Why this exists

Writing "security is important" in a specification is easy. Demonstrating a
habit of engaging carefully with the community's hard-won lessons is harder,
and more useful. These notes exist to:

- Make CoreNet's security reasoning visible and citable
- Give other projects and operators a shared reference for recurring topics
- Preserve what the community has learned from specific incidents
- Invite correction and refinement from readers with firsthand knowledge

## Editorial posture

- **Primary sources are cited heavily.** Where a note rests on secondhand
  accounts or community memory, that is stated plainly.
- **Other projects are peers.** The notes treat incidents as learning
  opportunities for everyone, not as cautionary tales at another project's
  expense. The projects whose experiences we draw from often did the hard,
  public work of exposing and fixing the issues we now benefit from
  understanding.
- **Uncertainty is surfaced.** When a claim is reconstructed rather than
  confirmed, the note says so.
- **Corrections are welcome.** Each note carries a revision history; readers
  with better information are encouraged to open an issue or discussion.
- **Focus is structural.** Lessons about design, defaults, and incentives
  matter more than particulars of any one implementation.

## Current notes

- [001 — Shared-secret broadcast and the Meshtastic 2024 MQTT incident](001-shared-secret-broadcast-meshtastic-2024.md) (first published 2026-04-19)

## Planned notes

Not commitments, just directions worth documenting:

- 002 — Bridge operator trust: what end-to-end encryption protects and what it doesn't
- 003 — Identity compromise and revocation in decentralized systems
- 004 — Metadata leakage in federated messaging
- 005 — Channel secret distribution at scale
- 006 — Part 97 and encryption: a practical guide for amateur deployments
- 007 — Flood amplification and the LAX↔SEA precedent (MeshCore Discussion #1736)

## Contributing

Corrections, additional citations, and proposals for new notes are welcome
via GitHub [issues](https://github.com/artbotterell/CoreNet/issues) and
[discussions](https://github.com/artbotterell/CoreNet/discussions).  The
goal of this series is to be accurate and useful to the broader community,
so outside perspectives — especially from people with direct involvement in
the events a note describes — are actively sought.

## Citation

Each note carries a stable filename (numbered prefix + slug). To cite a
specific note:

> CoreNet Security Notes #001, "Shared-secret broadcast and the Meshtastic
> 2024 MQTT incident," https://github.com/artbotterell/CoreNet/blob/master/security-notes/001-shared-secret-broadcast-meshtastic-2024.md

Notes are versioned via the revision history section at the end of each
document; cite the latest revision unless you need to pin to a specific
historical version.
