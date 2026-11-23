# Fashion Scout

A personal menswear scout run weekly by Claude. Each Sunday it emails five pieces that:

- **build a good wardrobe from scratch**, filling 26 essentials (foundations first) and tracking progress,
- fit your style (minimal, smart casual, streetwear) and your preference for a slightly loose fit, with no colour or brand bias,
- are **in stock in one of your sizes right now** (M or L, waist 32, UK 9), checked against the store's live data minutes before sending,
- justify their price with real fabric and construction quality (100% cotton, merino, corduroy, 230 GSM, full-grain leather…), never luxury,
- suit the season in North India and go with each other,
- have never been shown to you before.

Reply to the email (`1 love`, `2 skip, collar looks flimsy`, `3 bought L`, `4 save`) and it learns:
- brands and categories you like or skip,
- which wardrobe essentials you now own,
- your real size at each brand,
- items to watch for price drops or restocks.

## How it works

```
profile/profile.toml   you: size ranges, fit, dealbreakers, price caps, email  (edit this)
data/capsule.json      the 26-piece wardrobe being built from scratch
data/history.json      memory: every pick, your verdicts, learned sizes/taste    (updated each run)
data/stores.json       ~30 live-stock Indian stores + browser-verified marketplaces
scout/                 engine: catalog → filter → quality score → rank → verify → email
.claude/skills/fashion-scout/SKILL.md   the weekly procedure Claude follows
```

Weekly run:
1. Read your last reply and learn from it.
2. Plan the week: season, focus category, live sales.
3. Re-check your watchlist for price drops and restocks.
4. Scan ~50,000 products.
5. Claude looks at the photos and picks an edit.
6. Live-verify each pick.
7. Write stylist notes.
8. Email it with inline photos.
9. Commit memory back to this repo.

## Commands

```bash
python3 -m scout plan
python3 -m scout harvest [--group layers] [--refresh]
python3 -m scout sheet --top 36
python3 -m scout verify <product-url>
python3 -m scout pick 3 7 12 18 --wildcard 25
python3 -m scout digest out/picks.json
python3 -m scout feedback <run_id> --text "1 love, 2 skip"
python3 -m scout watch
python3 -m scout stats
python3 -m unittest tests.test_core
```

## Store coverage
- **Verified** (live per-size stock): Andamen, Rare Rabbit, Blackberrys, The Pant Project, Levi's, Fugazee, Bluorng, Jaywalking, The Bear House, Jack & Jones, Celio, Mr Button, US Polo, Jade Blue, Nicobar, Snitch, The Indian Garage Co, Wrogn, Powerlook, Bonkers Corner, Nobero, Campus Sutra, Dennis Lingo, Monkstory, Escaro, Thaely, 7-10, Gully Labs, Neeman's. Any other Shopify brand URL also verifies.
- **Browser-verified**: Flipkart, Tata CLiQ, Marks & Spencer, The Souled Store.
- **Not used**: Myntra, Ajio, Uniqlo, H&M, Zara and Amazon block automated access from cloud servers, so their stock can't be checked.
