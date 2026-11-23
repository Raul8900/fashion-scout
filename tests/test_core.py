import unittest

from scout import classify, feedback, history, quality, sizing

PROFILE = {"sizes": {"top": ["M", "L"], "waist_in": [32], "shoe_uk": [9], "brand": {"Snitch": {"top": "L"}}}}


class Sizing(unittest.TestCase):
    def want(self, cat, store="X", learned=None):
        return sizing.wanted_size(PROFILE, cat, store, learned)

    def test_letter_and_numeric_tops(self):
        w = self.want("shirt")
        self.assertEqual(sizing.size_status({"S": True, "M": True, "L": True}, w), ("in_stock", "M, L"))
        self.assertEqual(sizing.size_status({"S": True, "M": False, "L": True}, w), ("in_stock", "L"))
        self.assertEqual(sizing.size_status({"S-38": True, "M-40": False, "L-42": False}, w)[0], "sold_out")
        self.assertEqual(sizing.size_status({"38": True, "40": False, "42": True}, w), ("in_stock", "42"))
        self.assertEqual(sizing.size_status({"XL": True}, w)[0], "not_offered")
        self.assertFalse(sizing.label_matches("XM", w))

    def test_brand_override_and_learned(self):
        self.assertEqual(self.want("tshirt", "Snitch")["letters"], ["L"])
        self.assertEqual(self.want("tshirt", "Celio", {"Celio": {"top": "M"}})["letters"], ["M"])
        self.assertEqual(self.want("joggers")["letters"], ["M", "L"])  # joggers sold S/M/L

    def test_waist_and_shoe(self):
        self.assertEqual(sizing.size_status({"30": True, "32": True}, self.want("jeans")), ("in_stock", "32"))
        w = self.want("sneakers")
        self.assertEqual(sizing.size_status({"UK 8 / EU 42": True, "UK 9 / EU 43": True}, w)[0], "in_stock")
        self.assertEqual(sizing.size_status({"UK 9 / EU 43": False}, w)[0], "sold_out")
        self.assertTrue(sizing.label_matches("EU 42", w))

    def test_missing_profile(self):
        w = sizing.wanted_size({"sizes": {}}, "shirt", "X")
        self.assertEqual(sizing.size_status({"M": True}, w)[0], "unknown_profile")


class Capsule(unittest.TestCase):
    def test_slots(self):
        from scout import capsule
        it = {"title": "Heavyweight White Oversized T-Shirt", "category": "tshirt", "colours": ["white"]}
        self.assertEqual(capsule.matching_slots(it)[0]["id"], "tee-white")
        it2 = {"title": "Black Graphic Print Tee", "category": "tshirt", "colours": ["black"]}
        self.assertEqual(capsule.matching_slots(it2), [])
        h = {"capsule": {}}
        self.assertEqual(capsule.best_open_slot({"title": "Puffer Jacket", "category": "jacket"}, h, "summer"), None)
        self.assertEqual(capsule.best_open_slot({"title": "Puffer Jacket", "category": "jacket"}, h, "winter")["id"], "winter-jacket")
        capsule.fill(h, "x", {"title": "Brown Corduroy Overshirt", "category": "overshirt"})
        self.assertIn("overshirt", h["capsule"])


class Classify(unittest.TestCase):
    def test_categories(self):
        c = classify.categorize
        self.assertEqual(c("Black Jacquard Knit Polo T-Shirt 100% Cotton"), "polo")
        self.assertEqual(c("Grey Tie Dye Knit T-Shirt"), "tshirt")
        self.assertEqual(c("Textured Oversized Fit Knitted Sweater"), "sweater")
        self.assertEqual(c("Relaxed Fit Cotton Twill Shacket"), "overshirt")
        self.assertEqual(c("Brown Corduroy Overshirt"), "overshirt")
        self.assertEqual(c("Onward Co-ord Set"), "coord")
        self.assertEqual(c("Easy Stretch Chinos"), "chinos")
        self.assertEqual(c("The Munich Chukka Boots in Brown"), "boots")
        self.assertEqual(c("Statesman Horsebit Driving Loafers"), "loafers")

    def test_gender(self):
        self.assertEqual(classify.gender("Women's Linen Dress"), "women")
        self.assertEqual(classify.gender("Men's 501 Jeans"), "men")
        self.assertEqual(classify.gender("Thalia Embroidered Skater Mini Dress"), "women")


class Quality(unittest.TestCase):
    def test_good_beats_bad(self):
        good = quality.score("100% cotton oxford shirt, garment dyed, mother of pearl buttons", "shirt")
        bad = quality.score("Shirt. 100% polyester. Machine wash.", "shirt")
        unknown = quality.score("A stylish shirt for every occasion", "shirt")
        self.assertGreater(good["score"], 7.5)
        self.assertLess(bad["score"], 4)
        self.assertFalse(unknown["known"])
        self.assertLess(unknown["score"], 5)

    def test_composition(self):
        q = quality.score("Material: 70% Cotton & 30% Linen", "overshirt")
        self.assertEqual(q["composition"], {"cotton": 70, "linen": 30})
        q = quality.score("60% polyester 40% cotton tee", "tshirt")
        self.assertTrue(any("synthetic" in r for r in q["reasons"]))

    def test_shoes(self):
        self.assertGreater(quality.score("full grain leather upper, goodyear welted", "boots")["score"], 8)
        self.assertLess(quality.score("PU leather sneaker", "sneakers")["score"], 4)


class Feedback(unittest.TestCase):
    def test_parse(self):
        reply = "1 love\n2 skip, collar looks flimsy\n3 bought L\n4 save\nwildcard 👎\nAlso fewer black things please\n\nOn Sun, 29 Nov 2026 at 9:41, Scout <x@y> wrote:\n> 1. Overshirt"
        parsed, unparsed = feedback.parse(reply, 5)
        v = {p["pick"]: p["verdict"] for p in parsed}
        self.assertEqual(v, {1: "like", 2: "skip", 3: "bought", 4: "save", 5: "skip"})
        self.assertEqual(next(p for p in parsed if p["pick"] == 3)["size"], "L")
        self.assertIn("collar looks flimsy", next(p for p in parsed if p["pick"] == 2)["note"])
        self.assertEqual(unparsed, ["Also fewer black things please"])

    def test_multi(self):
        parsed, _ = feedback.parse("1, 3 yes; 2 nah", 4)
        self.assertEqual(sorted((p["pick"], p["verdict"]) for p in parsed), [(1, "like"), (2, "skip"), (3, "like")])

    def test_apply_learns(self):
        h = {"runs": [], "items": {}, "learned": {"sizes": {}, "weights": {}}, "rotation": {"index": 0}, "taste_notes": []}
        picks = [{"id": f"s:{i}", "url": f"https://s/{i}", "title": f"T{i}", "store": "Snitch" if i == 1 else "Celio",
                  "category": "overshirt", "colours": ["olive"], "price": 1999} for i in (1, 2)]
        history.record_run(h, "2026-11-29", "layers", picks)
        h["runs"][0]["thread_id"] = "t"
        res = feedback.apply_reply(h, "2026-11-29", "1 bought XL\n2 skip")
        self.assertEqual(len(res["applied"]), 2)
        self.assertEqual(h["learned"]["sizes"]["Snitch"]["top"], "XL")
        self.assertGreater(h["learned"]["weights"]["store:Snitch"], 0)
        self.assertLess(h["learned"]["weights"]["store:Celio"], 0)
        self.assertIn("overshirt", h["capsule"])          # bought -> wardrobe slot filled
        self.assertNotIn("colour:olive", h["learned"]["weights"])  # no colour learning
        self.assertTrue(h["runs"][0]["feedback_done"])


if __name__ == "__main__":
    unittest.main()
