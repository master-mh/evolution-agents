-- One autonomy flag per capability, and the §21.2 keys a publish channel
-- collides on (SPEC.md §0.4, §21.2, §27.1, §28 Phases 8-9; ADR-037).
--
-- §0.4 is the normative clause: "autonomy is granted tool by tool, phase by
-- phase". `external_publish` was gating two capabilities — `web_publish` and
-- `marketplace_listing` — which made it the only flag in the kernel that opened
-- more than one, and made `cmd_set_autonomy`'s own docstring ("there is
-- deliberately no switch that opens more than one") false as written.
--
-- **The two are not peers.** A page published by hand on a colony domain is
-- §28 Phase 8 — "landing-page drafts", "humans review all external use". A
-- marketplace listing is an offer to sell: Phase 9's "one narrow product class,
-- one merchant channel", with the legal identity and the liability reserves
-- that phase requires and this colony does not have. One flag collapsed a phase
-- boundary, so the defensible half could not be granted without the other.
--
-- **The new key is §0.4's own word, not an invention.** §0.4 lists six
-- prohibitions — no network from generated code, no real commerce, no external
-- communication, no real payments, no public publishing, no direct secret
-- access — and §27.1's defaults block carries five keys. "No real commerce" is
-- the one that never got one, and a marketplace listing is real commerce rather
-- than publishing; it was filed under the wrong prohibition. So `real_commerce`
-- is added and `external_publish` keeps its spec-given name over `web_publish`
-- alone. It is distinct from `real_spending`, which is §0.4's "no real
-- payments" and governs unattended *spend* rather than offering something for
-- sale; a colony can be forbidden to sell and still permitted to buy.
--
-- §27.1 is headed "development defaults, not economic recommendations", and the
-- precedent for extending it is `metabolic_acceleration_factor` — in
-- `operator_state` since migration 0014 and absent from §27.1's block. No
-- spec-named key is removed here.
--
-- **This migration can only narrow.** `real_commerce` ships 0 like every other
-- flag, so a colony that had `external_publish` on keeps exactly the publishing
-- it was granted and loses the marketplace half it was never separately
-- granted. That direction is deliberate: a schema change must never be able to
-- widen what a colony is permitted to do, because turning a capability on is an
-- operator act under §0.4 and a migration is not an operator.

-- §0.4's "no real commerce", which §27.1's block never carried a key for.
-- Ships false, like all five of its siblings.
ALTER TABLE operator_state ADD COLUMN real_commerce_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (real_commerce_enabled IN (0, 1));

-- §21.2's aggregation keys are "counterparty/domain/channel over a rolling
-- window". `domain` and `platform_account` have been on `external_action_
-- registry` since migration 0021, described there as "§21.2's 'domain used' and
-- 'platform account'" — and until now nothing keyed on either: they were
-- written at claim time, read back on the row, and named in no predicate
-- anywhere. These are the indexes the collision checks in `channel_registry`
-- now run against.
--
-- Neither column can be made NOT NULL here, and that is not an oversight:
-- whether a target is required depends on the channel's `target_kind`, which is
-- a registry fact rather than a schema one. An `email` legitimately has a
-- sending domain and no platform account, and a `web_publish` has a domain and
-- no counterparty. `channel_registry.check_action` fails closed on a missing
-- target instead, and `test_a_publish_channel_without_a_target_is_refused`
-- is what holds that line.
CREATE INDEX idx_external_actions_domain
    ON external_action_registry (domain) WHERE domain IS NOT NULL;
CREATE INDEX idx_external_actions_platform_account
    ON external_action_registry (platform_account) WHERE platform_account IS NOT NULL;

-- The duplicate check for a channel that addresses nobody. There is no person
-- to key it on, so it is keyed on the artifact: ADR-035 made an artifact's
-- identity its content hash precisely so that "duplicated artifacts with new
-- names" (§11.3) is unrepresentable rather than merely detectable, and this is
-- the first check that spends that identity.
CREATE INDEX idx_external_actions_artifact
    ON external_action_registry (artifact_id) WHERE artifact_id IS NOT NULL;
