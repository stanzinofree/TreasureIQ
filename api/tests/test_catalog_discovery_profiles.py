from treasureiq.catalog.discovery_profiles import profile_for_base


def test_known_base_profile_adds_specialized_hints() -> None:
    profile = profile_for_base("wordpress_agid")
    assert "area personale" in profile.service_markers
    assert ("urbi", "urbi") in profile.provider_markers


def test_unknown_base_keeps_generic_fallback() -> None:
    profile = profile_for_base("vendor_non_riconosciuto")
    assert profile.base_platform is None
    assert profile.service_markers == ()
