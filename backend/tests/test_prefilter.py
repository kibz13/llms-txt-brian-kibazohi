"""
Prefilter tests — URL normalisation, filtering, pre-crawl scoring,
and multi-language deduplication.
No network calls or mocks required.
"""

from prefilter import (
    detect_lang_prefix,
    filter_language_variants,
    filter_template_explosion,
    is_non_preferred_lang,
    normalise_url,
    path_shape,
    same_domain,
    score_url,
    should_skip,
)


# ---------------------------------------------------------------------------
# score_url
# ---------------------------------------------------------------------------

def test_score_url_docs_path():
    # guide type, no URL boost — /configuration matches no boost pattern
    assert score_url("https://example.com/docs/configuration") == 8


def test_score_url_pricing_path():
    assert score_url("https://example.com/pricing") == 6


def test_score_url_blog_path():
    assert score_url("https://example.com/blog/my-post") == 4


def test_score_url_contact_path():
    assert score_url("https://example.com/contact") == 2


def test_score_url_getting_started_boosted_above_generic_docs():
    # /getting-started gets +5 URL boost on top of the guide base score
    assert score_url("https://example.com/docs/getting-started") > score_url("https://example.com/docs/configuration")


def test_score_url_changelog_penalized():
    # /changelog gets -4 URL boost so it scores below a neutral guide page
    assert score_url("https://example.com/changelog") < score_url("https://example.com/docs/configuration")


def test_score_url_docs_ranks_above_blog():
    assert score_url("https://example.com/docs/api") > score_url("https://example.com/blog/post")


def test_score_url_shallow_unknown_ranks_above_deep_unknown():
    assert score_url("https://example.com/about-us") > score_url("https://example.com/a/b/c/d")


def test_score_url_unknown_path_returns_positive():
    assert score_url("https://example.com/some/unknown/path") >= 1


# ---------------------------------------------------------------------------
# normalise_url
# ---------------------------------------------------------------------------

def test_normalise_strips_trailing_slash():
    assert normalise_url("https://example.com/about/") == "https://example.com/about"


def test_normalise_preserves_root_slash():
    assert normalise_url("https://example.com/") == "https://example.com/"


def test_normalise_lowercases_scheme_and_host():
    assert normalise_url("HTTPS://Example.COM/About") == "https://example.com/About"


def test_normalise_removes_default_https_port():
    assert normalise_url("https://example.com:443/page") == "https://example.com/page"


def test_normalise_removes_default_http_port():
    assert normalise_url("http://example.com:80/page") == "http://example.com/page"


def test_normalise_keeps_non_default_port():
    assert normalise_url("https://example.com:8080/page") == "https://example.com:8080/page"


def test_normalise_removes_fragment():
    assert normalise_url("https://example.com/page#section") == "https://example.com/page"


def test_normalise_deduplicates_trailing_slash_variant():
    # Both forms normalise to the same string
    assert normalise_url("https://example.com/docs") == normalise_url("https://example.com/docs/")


# ---------------------------------------------------------------------------
# same_domain
# ---------------------------------------------------------------------------

def test_same_domain_true():
    assert same_domain("https://example.com", "https://example.com/about")


def test_same_domain_false():
    assert not same_domain("https://example.com", "https://other.com/page")


def test_same_domain_www_vs_apex():
    # Submitted URL has www, sitemap URLs use apex — must match
    assert same_domain("https://www.openai.com", "https://openai.com/blog/post")


def test_same_domain_apex_vs_www():
    # Submitted URL is apex, sitemap uses www — must match
    assert same_domain("https://openai.com", "https://www.openai.com/about")


# ---------------------------------------------------------------------------
# should_skip
# ---------------------------------------------------------------------------

def test_should_skip_image():
    assert should_skip("https://example.com/logo.png")


def test_should_skip_pdf():
    assert should_skip("https://example.com/report.pdf")


def test_should_skip_cdn_cgi():
    assert should_skip("https://example.com/cdn-cgi/trace")


def test_should_skip_pagination_param():
    assert should_skip("https://example.com/blog?page=2")


def test_should_skip_utm_param():
    assert should_skip("https://example.com/?utm_source=google")


def test_should_skip_utm_variant():
    assert should_skip("https://example.com/pricing?utm_campaign=launch&utm_medium=email")


def test_should_skip_tracking_param():
    assert should_skip("https://example.com/post?gclid=abc123")


def test_should_not_skip_unknown_param():
    # Unrecognised query params are still allowed through
    assert not should_skip("https://example.com/docs?version=2")


def test_should_not_skip_clean_url():
    assert not should_skip("https://example.com/about")


# PATH_BLACKLIST

def test_should_skip_tag_path():
    assert should_skip("https://example.com/tag/python")


def test_should_skip_category_path():
    assert should_skip("https://example.com/category/news/article")


def test_should_skip_login_path():
    assert should_skip("https://example.com/login")


def test_should_skip_login_subpath():
    assert should_skip("https://example.com/login/oauth")


def test_should_skip_terms_path():
    assert should_skip("https://example.com/terms")


def test_should_skip_feed_path():
    assert should_skip("https://example.com/feed/")


def test_should_not_skip_docs_path():
    assert not should_skip("https://example.com/docs/getting-started")


def test_should_skip_colon_pagination():
    assert should_skip("https://www.example.it/ita/list/news/page:9")


def test_should_skip_colon_pagination_any_number():
    assert should_skip("https://www.example.it/fra/list/news/page:11")


def test_should_not_skip_path_containing_page_word():
    # "page" as part of a content slug should not be skipped
    assert not should_skip("https://example.com/docs/landing-page-guide")


# ---------------------------------------------------------------------------
# detect_lang_prefix
# ---------------------------------------------------------------------------

_RENTANDGO_URLS = [
    "https://www.example.it/ita/list/news",
    "https://www.example.it/fra/list/news",
    "https://www.example.it/eng/list/news",
    "https://www.example.it/pol/list/news",
    "https://www.example.it/deu/list/news",
]


def test_detect_lang_prefix_returns_english_when_present():
    assert detect_lang_prefix(_RENTANDGO_URLS) == "eng"


def test_detect_lang_prefix_prefers_en_over_eng():
    urls = [
        "https://example.com/en/about",
        "https://example.com/fr/about",
        "https://example.com/de/about",
    ]
    assert detect_lang_prefix(urls) == "en"


def test_detect_lang_prefix_returns_none_for_single_language():
    # Only one language code found — not a multi-language site
    urls = [
        "https://example.com/en/about",
        "https://example.com/en/pricing",
    ]
    assert detect_lang_prefix(urls) is None


def test_detect_lang_prefix_returns_none_for_no_lang_codes():
    urls = [
        "https://example.com/docs/getting-started",
        "https://example.com/blog/my-post",
    ]
    assert detect_lang_prefix(urls) is None


def test_detect_lang_prefix_falls_back_to_most_common():
    # No English variant — pick the language with most URLs
    urls = [
        "https://example.com/ita/page1",
        "https://example.com/ita/page2",
        "https://example.com/ita/page3",
        "https://example.com/fra/page1",
    ]
    assert detect_lang_prefix(urls) == "ita"


# ---------------------------------------------------------------------------
# filter_language_variants
# ---------------------------------------------------------------------------

def test_filter_language_variants_keeps_preferred_only():
    filtered = filter_language_variants(_RENTANDGO_URLS)
    assert all("/eng/" in u for u in filtered)
    assert len(filtered) == 1


def test_filter_language_variants_keeps_non_lang_urls():
    urls = _RENTANDGO_URLS + ["https://www.example.it/"]
    filtered = filter_language_variants(urls)
    assert "https://www.example.it/" in filtered


def test_filter_language_variants_unchanged_single_language():
    urls = [
        "https://example.com/docs/api",
        "https://example.com/blog/post",
    ]
    assert filter_language_variants(urls) == urls


def test_filter_language_variants_drops_single_lang_mixed_with_canonical():
    # Only one language code (Italian) found — detect_lang_prefix returns None.
    # But non-prefixed canonical URLs exist, so /it/ variants should be dropped.
    urls = [
        "https://example.com/docs/api",
        "https://example.com/docs/guide",
        "https://example.com/it/docs/api",
        "https://example.com/it/docs/guide",
    ]
    filtered = filter_language_variants(urls)
    assert "https://example.com/docs/api" in filtered
    assert "https://example.com/docs/guide" in filtered
    assert "https://example.com/it/docs/api" not in filtered
    assert "https://example.com/it/docs/guide" not in filtered


def test_filter_language_variants_unchanged_single_lang_all_prefixed():
    # All URLs share the same language prefix — it's a mono-language site.
    # Nothing to filter; return as-is.
    urls = [
        "https://example.com/it/docs/api",
        "https://example.com/it/blog/post",
    ]
    assert filter_language_variants(urls) == urls


# ---------------------------------------------------------------------------
# is_non_preferred_lang
# ---------------------------------------------------------------------------

def test_is_non_preferred_lang_true_for_other_lang():
    assert is_non_preferred_lang("https://example.it/ita/news", "eng")


def test_is_non_preferred_lang_false_for_preferred():
    assert not is_non_preferred_lang("https://example.it/eng/news", "eng")


def test_is_non_preferred_lang_false_for_no_lang_prefix():
    assert not is_non_preferred_lang("https://example.com/docs/api", "eng")


# ---------------------------------------------------------------------------
# path_shape
# ---------------------------------------------------------------------------

def test_path_shape_location_segment():
    assert path_shape("https://www.weatherbug.com/weather-forecast/now/plandome-heights-ny-11030") == \
        "/weather-forecast/now/:location"

def test_path_shape_uuid_segment():
    assert path_shape("https://example.com/items/a3f9c2d1-4b5e-11ec-81d3-0242ac130003") == \
        "/items/:uuid"

def test_path_shape_numeric_id():
    assert path_shape("https://example.com/products/98765") == "/products/:id"

def test_path_shape_slug_with_id():
    assert path_shape("https://example.com/products/royal-oak-sofa-12345") == "/products/:id"

def test_path_shape_year_segment():
    assert path_shape("https://example.com/blog/2024/my-post") == "/blog/:year/my-post"

def test_path_shape_date_segment():
    assert path_shape("https://example.com/news/2024-05-20/article-title") == \
        "/news/:date/article-title"

def test_path_shape_static_docs_unchanged():
    assert path_shape("https://example.com/docs/authentication") == "/docs/authentication"

def test_path_shape_root():
    assert path_shape("https://example.com/") == "/"


# ---------------------------------------------------------------------------
# filter_template_explosion
# ---------------------------------------------------------------------------

def _make_weather_urls(n: int) -> list[str]:
    cities = [f"city-name-{i}-ca-{90000 + i:05d}" for i in range(n)]
    return [f"https://weather.example.com/forecast/now/{c}" for c in cities]

def test_explosion_caps_high_cardinality_group():
    urls = _make_weather_urls(50)
    result = filter_template_explosion(urls, max_per_shape=10, explosion_threshold=20)
    assert len(result) == 10

def test_explosion_keeps_group_below_threshold():
    # 15 docs pages — under explosion_threshold=20, all pass through
    urls = [f"https://example.com/docs/page-{i}" for i in range(15)]
    result = filter_template_explosion(urls, max_per_shape=10, explosion_threshold=20)
    assert len(result) == 15

def test_explosion_does_not_affect_unrelated_groups():
    weather_urls = _make_weather_urls(50)
    docs_urls = [f"https://example.com/docs/page-{i}" for i in range(10)]
    all_urls = weather_urls + docs_urls
    result = filter_template_explosion(all_urls, max_per_shape=10, explosion_threshold=20)
    # Weather capped at 10, docs all pass through
    assert len(result) == 20
    assert all(u in result for u in docs_urls)

def test_explosion_preserves_order():
    urls = _make_weather_urls(50)
    result = filter_template_explosion(urls, max_per_shape=10, explosion_threshold=20)
    assert result == urls[:10]

def test_explosion_empty_list():
    assert filter_template_explosion([]) == []
