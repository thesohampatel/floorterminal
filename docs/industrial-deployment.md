# Industrial deployment and acceptance

FloorTerminal is line-side reporting and coordination software. It does
not read or write PLC logic, perform interlocking, command motion, acknowledge a
safety alarm, or replace emergency-stop, guarding, permit-to-work, or lockout/tagout
procedures. Treat every connector action as an administrative business-system
update, never as proof that equipment is safe.

## Standards alignment boundary

The project uses the following publications as engineering guidance. Repository
controls are not certification and do not establish organizational or site
conformity:

- [NIST SP 800-218 SSDF 1.1](https://csrc.nist.gov/pubs/sp/800/218/final) for
  secure-development vocabulary, change review, vulnerability handling, release
  integrity, and provenance.
- [IEC 62443-4-1:2018](https://webstore.iec.ch/en/publication/33615) as guidance
  for security requirements, secure design and implementation, verification,
  defect management, patch management, and end-of-life planning.
- [ISO 9241-210:2019](https://www.iso.org/standard/77520.html) as guidance for
  human-centred interactive-system design and usability validation.

Supporting evidence for these is kept in [requirements traceability](traceability.md),
[accessibility evidence](accessibility.md), and [product lifecycle](lifecycle.md).

Functional-safety standards, including IEC 61508 and machine-specific standards,
remain outside the product claim. A qualified site integrator must determine all
applicable legal, safety, cybersecurity, privacy, accessibility, labor, and record-
retention obligations for the facility and jurisdiction.

## Required site acceptance

Before production use, record evidence for every item:

1. Confirm the terminal is outside all safety functions and cannot directly
   command machinery.
2. Run the executable as a dedicated unprivileged account on a supported,
   patched graphical operating system.
3. Restrict physical, shell, remote-management, removable-media, and boot access.
4. Verify outbound firewall rules, DNS, CA trust, connector host allowlists,
   credential scope, credential rotation, and server-side idempotency.
5. Test report creation, ambiguous timeout, duplicate suppression, queue recovery,
   participant changes, completion, asset-state failure, and partial-capability
   behavior against a non-production integration.
6. Validate every configured station, failure type, team, destination, asset,
   location, escalation, retention period, locale, and screen resolution.
7. Test cold boot, power loss during each workflow state, corrupt state recovery,
   storage-low behavior, clock correction, network loss, process crash, and
   supervisor restart.
8. Conduct operator usability testing with gloves and the installed touchscreen;
   verify touch targets, contrast, status redundancy, dialog bounds, and readable
   text at the deployed viewing distance. Start from the measured figures in
   [accessibility evidence](accessibility.md) and record the site's decision on the
   two open items listed there.
9. Define backup, restore, log export, incident response, vulnerability intake,
   update, rollback, and end-of-life ownership.
10. Obtain formal approval from site operations, engineering, safety, IT/security,
    privacy/legal, and the accountable system owner.

## Operational evidence

Retain the release checksum manifest, SPDX SBOM, build record, configuration
approval, connector review, acceptance results, risk assessment, training record,
and rollback package. Monitor storage, time synchronization, connector failures,
queued events, remote rate limits, OS health, and security advisories. Re-run the
acceptance scope after any application, OS, connector, network, station-layout, or
business-workflow change.
