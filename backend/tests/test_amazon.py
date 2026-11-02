"""Amazon parsing and filter mapping, against the shape of a real amazon.in response."""

from cupid import amazon
from cupid.amazon import AmazonSearch

RESPONSE = {
    "organic_results": [
        {"asin": "B0FDW55HNT", "title": "Women's Rayon Printed Anarkali Kurta and Pant with Dupatta Set",
         "extracted_price": 665, "price": "₹665", "extracted_old_price": 2999, "brand": "KLOSIA",
         "rating": 4.1, "reviews": 11100, "bought_last_month": "5K+ bought in past month",
         "link_clean": "https://www.amazon.in/dp/B0FDW55HNT/",
         "thumbnail": "https://m.media-amazon.com/images/I/71I53evweVL._AC_UL320_.jpg"},
        {"asin": "B0SPONSOR1", "title": "Sponsored kurta", "sponsored": True, "thumbnail": "https://x/y.jpg"},
        {"asin": "B0MENS0001", "title": "Men's Cotton Kurta", "thumbnail": "https://x/m.jpg"},
        {"asin": "B0NOIMAGE1", "title": "Kurta without a photo"},
    ],
    "filters": {
        "colour": [{"name": "Black", "rh": "p_n_size_two_browse-vebin:1975317031"},
                   {"name": "Greys", "rh": "p_n_size_two_browse-vebin:1975322031"}],
        "material": [{"name": "Cotton Blend", "rh": "p_n_g-101017721711111:1"},
                     {"name": "Art Silk", "rh": "p_n_g-101017721711111:2"}],
        "fit_type": [{"name": "Relaxed", "rh": "p_n_g-1003486863111:41594812031"},
                     {"name": "Regular", "rh": "p_n_g-1003486863111:41594813031"}],
        "category": [{"name": "Women's Indian Clothing", "rh": "n:1968253031"},
                     {"name": "Women's Kurtas & Kurtis", "rh": "n:1968255031"}],
        "women_s_size": [{"name": "M", "rh": "p_n_size_five_browse-vebin:1975368031"}],
    },
}


def test_parse_keeps_real_womens_listings_only():
    offers = amazon.parse_results(RESPONSE)
    assert [o["id"] for o in offers] == ["B0FDW55HNT"]
    o = offers[0]
    assert (o["price"], o["old_price"], o["rating"], o["reviews"]) == (665, 2999, 4.1, 11100)
    assert o["bought"] == "5K+ bought last month"
    assert o["link"] == "https://www.amazon.in/dp/B0FDW55HNT/"
    assert o["thumbnail_url"].endswith("._AC_UL900_.jpg"), "asks Amazon for the big photo"


def test_filters_map_to_cupids_attributes_and_back():
    f = amazon.parse_filters(RESPONSE)
    assert amazon.to_vocab("colour", "Greys") == ("colour", "grey")
    assert amazon.to_vocab("material", "Art Silk") == ("fabric", "silk")
    assert amazon.to_vocab("fit_type", "Regular") is None, "no Cupid meaning, so never used"
    assert amazon.option_for(f, "colour", "black") == ("Black", "p_n_size_two_browse-vebin:1975317031")
    assert amazon.option_for(f, "fabric", "cotton") == ("Cotton Blend", "p_n_g-101017721711111:1")
    assert amazon.option_for(f, "fit", "fitted") is None
    assert amazon.category_node(f, "kurta") == "n:1968255031"
    menu = {m["label"]: m for m in amazon.filter_menu(f)}
    assert list(menu) == ["Size", "Colour", "Fit", "Material"], "clothing filters only, in a set order"
    assert menu["Size"]["options"] == [{"name": "M", "rh": "p_n_size_five_browse-vebin:1975368031", "label": "M"}]


def test_search_key_separates_filtered_searches():
    assert AmazonSearch(k="women kurta").key() != AmazonSearch(k="women kurta", rh="n:1968255031").key()


def test_occasion_goes_into_the_search():
    assert amazon.answer_search("dresses", "wedding").k == "women wedding guest dress"
    assert amazon.answer_search("dresses", "date").k == "women date night dress"
    assert amazon.answer_search("dresses", "date").key() != amazon.answer_search("dresses", "work").key()


def test_nightwear_and_fabric_are_never_outfits():
    junk = ["Cotton Blend Womens Korean Night Dress || Full Pyjama Set", "Women Nightsuit Set",
            "Women's Lounge Co-Ord Set", "Women Unstitched Dress Material", "Women Pajama Set",
            "Women's Satin Nightgown", "Womens Halloween Costume Dress"]
    data = {"organic_results": [{"asin": f"B{i}", "title": t, "thumbnail": "https://x/y.jpg"} for i, t in enumerate(junk)]
            + [{"asin": "BOK", "title": "Women Floral Maxi Dress", "thumbnail": "https://x/y.jpg"}]}
    assert [o["id"] for o in amazon.parse_results(data)] == ["BOK"]


def test_several_values_of_one_filter_combine_with_a_bar():
    codes = ["n:1968255031", "p_n_size_two_browse-vebin:1975317031", "p_n_size_two_browse-vebin:1975329031"]
    rh = amazon.combine_rh(codes)
    assert rh == "n:1968255031,p_n_size_two_browse-vebin:1975317031|1975329031"
    assert amazon.split_rh(rh) == codes


def test_colour_choices_accept_what_the_photo_can_show():
    assert amazon.visible_colours(["Reds"]) == {"red", "maroon"}
    assert amazon.visible_colours(["Black", "Blues"]) == {"black", "blue", "navy", "teal"}
