# Offline tests for the pre-enrichment dedupe + the final-records cap.
# No DB / network / paid actor calls. Run from the backend dir:
#   PYTHONPATH=. ./venv/bin/python tests/test_dedupe_seeds.py

from agent.schema import GoogleSeed, ContractorRow
from agent.dedupe import dedupe_seeds
from agent.pipeline import _apply_cap


def _seed(**kw):
    base = dict(place_id="", business_name="X", city="Tampa", zip_code="33602")
    base.update(kw)
    return GoogleSeed(**base)


def test_dedupe_by_phone():
    seeds = [
        _seed(place_id="p1", business_name="Talmadge Drywall", phone="813-555-1234", email=None),
        _seed(place_id="p2", business_name="Talmadge Drywall LLC", phone="(813) 555-1234", email="info@tal.com"),
    ]
    out = dedupe_seeds(seeds)
    assert len(out) == 1, f"expected 1, got {len(out)}"
    assert set(out[0].merged_place_ids) == {"p1", "p2"}, out[0].merged_place_ids
    # survivor backfilled the missing email from the twin
    assert out[0].email == "info@tal.com", out[0].email
    print("✅ dedupe by phone (+ place_id merge + email backfill)")


def test_dedupe_by_domain():
    seeds = [
        _seed(place_id="a", business_name="West Star", website="https://weststar.com", phone=None),
        _seed(place_id="b", business_name="West Star Interiors", website="http://www.weststar.com/contact", phone=None),
    ]
    out = dedupe_seeds(seeds)
    assert len(out) == 1, f"expected 1, got {len(out)}"
    assert set(out[0].merged_place_ids) == {"a", "b"}
    print("✅ dedupe by domain")


def test_dedupe_by_name_loc():
    seeds = [
        _seed(place_id="x", business_name="Stuller Drywall Inc", phone=None, website=None, zip_code="33612"),
        _seed(place_id="y", business_name="Stuller Drywall", phone=None, website=None, zip_code="33612"),
    ]
    out = dedupe_seeds(seeds)
    assert len(out) == 1, f"name+loc should collapse, got {len(out)}"
    print("✅ dedupe by name+location (suffix-insensitive)")


def test_distinct_preserved_and_ordered():
    seeds = [
        _seed(place_id="1", business_name="A Drywall", phone="813-555-0001"),
        _seed(place_id="2", business_name="B Painting", phone="813-555-0002"),
        _seed(place_id="3", business_name="C Remodel", phone="813-555-0003"),
    ]
    out = dedupe_seeds(seeds)
    assert len(out) == 3, f"distinct seeds must survive, got {len(out)}"
    assert [s.place_id for s in out] == ["1", "2", "3"], "order must be stable"
    print("✅ distinct seeds preserved + order stable")


def _row(tier, rating, name):
    return ContractorRow(business_name=name, tier=tier, google_rating=rating)


def test_cap_keeps_best_tiers():
    rows = [
        _row("TIER_3_HANDYMAN", 4.9, "handyman"),
        _row("TIER_1_DRYWALL", 4.1, "drywall-a"),
        _row("TIER_1_DRYWALL", 4.8, "drywall-b"),
        _row("TIER_2_PAINTER", 5.0, "painter"),
    ]
    capped = _apply_cap(rows, 2)
    assert len(capped) == 2, len(capped)
    names = {r.business_name for r in capped}
    # both TIER_1 drywall kept (best tier), higher rating first
    assert names == {"drywall-a", "drywall-b"}, names
    assert capped[0].business_name == "drywall-b", "higher rating within tier first"
    print("✅ cap keeps strongest tiers (drywall over painter/handyman)")


def test_cap_noop_when_under_limit():
    rows = [_row("TIER_1_DRYWALL", 4.0, "a"), _row("TIER_2_PAINTER", 4.0, "b")]
    assert _apply_cap(rows, 5000) is rows, "under limit → unchanged list"
    assert len(_apply_cap(rows, 0)) == 2, "0/None means no cap"
    print("✅ cap is a no-op below the limit")


if __name__ == "__main__":
    test_dedupe_by_phone()
    test_dedupe_by_domain()
    test_dedupe_by_name_loc()
    test_distinct_preserved_and_ordered()
    test_cap_keeps_best_tiers()
    test_cap_noop_when_under_limit()
    print("\n🎉 all dedupe + cap tests passed")
