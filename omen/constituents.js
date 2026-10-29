// OMEN constituents — the one list of the Polymarket markets behind the Bull / Bear pair
// (and the monitor's China and Macro side-indexes), in dated vintages.
//
// This file used to exist five times: POLY_IDS in update-market-data.py and a hand-typed
// MARKETS / CONSTITUENTS array in index.html, indexes.html, gauge.html and
// polymarket-ai-index.html. Three markets had already left the live basket (one expired
// 31 Jul, one 30 Sep, one was delisted 4 Sep) while every page still said "twenty".
// Now the fetcher (update-market-data.py) parses the JSON literal below, every page loads
// this script, and test_constituents.py / test-constituents.mjs fail if a page grows a
// copy of its own again.
//
// Shape: a plain JSON object after the `=`, nothing else — Python reads it with
// json.loads, not a JS engine. Keep it that way.
//
// Vintages: a market is a member on day D when  from <= D < to  (`to` absent = open-ended).
//   from      the day it joined the basket (the original twenty: the 2026-07-10 curation)
//   to        the day it left — a resolution, a delisting, or a curation decision. Set it
//             when a market is retired on purpose; a market that merely resolves drops out
//             of the live index by itself (Gamma marks it closed) and `to` just records when.
//   proposed  true = a successor written down but not yet curated into the basket. Never a
//             member, whatever its dates say; delete the flag to activate it.
//   role      names a market a single signal reads by job rather than by id, so a successor
//             takes the job over on its `from` date (newest live `from` wins; at most one
//             live member per role per day):
//               bubble      the gauge's prediction family and the regime's single-market trip
//               recession   the monitor's macro family (US recession odds)
//               fed_cuts    the monitor's macro family (easing-cycle odds)
//               china_top3  the monitor's macro family and the China single-signal trip
//               china_best  the claims-watch China read
//
// The China and Macro side-indexes are watched the same way (coverage.sides.china /
// .macro) but never drive the verdict: a thin side-index warns, it does not roll.
//
// The roll rule (index.html, update-market-data.py): a side with fewer than `roll_floor`
// live markets has no direction read — the verdict goes to "No edge · basket rolling" until
// the next vintage is priced. The fetcher's `coverage` block in market-data.json counts
// live markets per side, the next expiry cliff and the markets inside `horizon_days` of it,
// and the refresh run warns (and alerts) when half a side expires within the horizon.
//
// 16 of the 17 live markets of the 2026 vintage resolve on 2027-01-01. The 2027 successors
// below are `proposed`: Polymarket had listed 2027 versions of only some themes on
// 2026-10-22 — see BACKLOG.md "Constituent roll — the 2027 vintage" for the themes still
// without one, and for the from-date choice (overlap lets the chain-linked history absorb
// the change; a cliff-day swap does not).
window.OMEN_CONSTITUENTS = {
  "curated": "2026-07-10",
  "roll_floor": 3,
  "horizon_days": 30,
  "markets": [
    { "id": "676829",  "side": "bull", "theme": "tech",    "htype": "event",      "label": "GPT-6 released by Dec 31, 2026",
      "slug": "gpt-6-released-by", "from": "2026-07-10", "to": "2026-09-04",
      "note": "no longer returned by Gamma from 2026-09-04 (delisted); left the live index that day" },
    { "id": "653788",  "side": "bull", "theme": "tech",    "htype": "structural", "label": "OpenAI announces AGI before 2027",
      "slug": "openai-announces-it-has-achieved-agi-before-2027", "from": "2026-07-10" },
    { "id": "676837",  "side": "bull", "theme": "tech",    "htype": "event",      "label": "AI wins IMO gold medal in 2026",
      "slug": "ai-wins-imo-gold-medal-in-2026", "from": "2026-07-10" },
    { "id": "1087074", "side": "bull", "theme": "tech",    "htype": "structural", "label": "Any model hits 1550 Chatbot Arena by Dec 31",
      "slug": "chatbot-arena-how-high-will-ai-score-by-december-31", "from": "2026-07-10" },
    { "id": "656312",  "side": "bull", "theme": "capital", "htype": "event",      "label": "OpenAI IPO by Dec 31, 2026",
      "slug": "openai-ipo-by", "from": "2026-07-10" },
    { "id": "656313",  "side": "bull", "theme": "capital", "htype": "event",      "label": "OpenAI $1t+ IPO before 2027",
      "slug": "openai-1t-ipo-before-2027", "from": "2026-07-10" },
    { "id": "2413330", "side": "bull", "theme": "capital", "htype": "event",      "label": "Anthropic IPO by Dec 31, 2026",
      "slug": "anthropic-ipo-by", "from": "2026-07-10" },
    { "id": "2109881", "side": "bull", "theme": "capital", "htype": "structural", "label": "Anthropic market cap flips BTC by Dec 31",
      "slug": "will-anthropic-flip-btc-by-december-31", "from": "2026-07-10" },
    { "id": "676804",  "side": "bull", "theme": "tech",    "htype": "event",      "label": "OpenAI consumer hardware product by Dec 31, 2026",
      "slug": "will-openai-launch-a-consumer-hardware-product-by", "from": "2026-07-10" },
    { "id": "2487206", "side": "bull", "theme": "tech",    "htype": "event",      "label": "Next Mythos-class model by Sep 30, 2026",
      "slug": "next-mythos-class-model-released-by", "from": "2026-07-10", "to": "2026-09-01",
      "note": "expired 2026-09-30 by its own terms; Gamma marked it closed on 2026-09-01" },
    { "id": "2255930", "side": "bull", "theme": "tech",    "htype": "event",      "label": "AI data center in space by Dec 31, 2027",
      "slug": "ai-data-center-in-space-by", "from": "2026-07-10" },

    { "id": "691340",  "side": "bear", "theme": "mkt", "htype": "structural", "label": "AI bubble burst in 2026 (3+ crash triggers)",
      "slug": "ai-bubble-burst-by", "from": "2026-07-10", "role": "bubble", "reflexive": true },
    { "id": "676827",  "side": "bear", "theme": "mkt", "htype": "event",      "label": "OpenAI acquired before 2027",
      "slug": "openai-acquired-before-2027", "from": "2026-07-10" },
    { "id": "676846",  "side": "bear", "theme": "mkt", "htype": "event",      "label": "Anthropic acquired before 2027",
      "slug": "anthropic-acquired-before-2027", "from": "2026-07-10" },

    { "id": "2787889", "side": "bear", "theme": "gov", "htype": "structural", "label": "US gov removes access to a major AI model in 2026",
      "slug": "us-government-removes-public-access-to-another-major-ai-model-in-2026-20260703202936862", "from": "2026-07-10" },
    { "id": "2787891", "side": "bear", "theme": "gov", "htype": "structural", "label": "US gov removes access to an Anthropic model in 2026",
      "slug": "us-government-removes-public-access-to-another-anthropic-ai-model-in-2026-20260703203121674", "from": "2026-07-10" },
    { "id": "2787890", "side": "bear", "theme": "gov", "htype": "structural", "label": "US gov removes access to a Chinese AI model in 2026",
      "slug": "us-government-removes-public-access-to-a-major-chinese-ai-model-in-2026-20260703203328223", "from": "2026-07-10" },
    { "id": "2698575", "side": "bear", "theme": "gov", "htype": "event",      "label": "Trump orders federal review of AI releases by Jul 31",
      "slug": "trump-orders-federal-review-for-ai-model-releases-by-may-31", "from": "2026-07-10", "to": "2026-08-01",
      "note": "expired 2026-07-31 by its own terms" },
    { "id": "676842",  "side": "bear", "theme": "gov", "htype": "event",      "label": "US enacts AI safety bill before 2027",
      "slug": "us-enacts-ai-safety-bill-before-2027", "from": "2026-07-10" },
    { "id": "2839991", "side": "bear", "theme": "gov", "htype": "event",      "label": "Any state enacts data center moratorium by Dec 31",
      "slug": "will-any-state-enact-a-data-center-moratorium-by-december-31-20260707003733282", "from": "2026-07-10" },

    { "id": "6017629", "side": "bull", "theme": "tech",    "htype": "structural", "label": "GPT Astra 6.1+ debuts at 1440+ on Text Arena by Jun 30, 2027",
      "slug": "gpt-astra-6pt1-text-arena-debut-20261020", "from": "2026-12-15", "proposed": true,
      "note": "2027 successor to 1087074 (Arena 1550 by Dec 31) – a named-model debut ladder, not an any-model threshold; curate or replace" },
    { "id": "3957123", "side": "bull", "theme": "capital", "htype": "event",      "label": "OpenAI IPO by Jun 30, 2027",
      "slug": "openai-ipo-by", "from": "2026-12-15", "proposed": true,
      "note": "2027 successor to 656312 (OpenAI IPO by Dec 31, 2026); a Dec 31, 2027 leg did not exist on 2026-10-22" },
    { "id": "3887676", "side": "bull", "theme": "capital", "htype": "structural", "label": "Anthropic IPO closing market cap above $1.5T (by Dec 31, 2027)",
      "slug": "anthropic-ipo-closing-market-cap-above", "from": "2026-12-15", "proposed": true,
      "note": "2027 successor to 2109881 / 2413330 – prices the IPO valuation rather than the IPO date" },
    { "id": "4838928", "side": "bear", "theme": "mkt",     "htype": "structural", "label": "AI bubble burst by Jun 30, 2027",
      "slug": "ai-bubble-burst-by", "from": "2027-01-01", "proposed": true, "role": "bubble", "reflexive": true,
      "note": "2027 successor to 691340, the gauge's bubble market. Its horizon is six months, not twelve: revisit the pred_bubble 0–40% range in OMEN.GAUGE_REFS when it goes live" },
    { "id": "5126779", "side": "bear", "theme": "gov",     "htype": "event",      "label": "Indiana enacts a data center moratorium by Dec 31, 2027",
      "slug": "indiana-enacts-data-center-moratorium-by-20260929", "from": "2026-12-15", "proposed": true,
      "note": "2027 successor to 2839991 (any state by Dec 31) – a single-state leg; Polymarket lists per-state ladders only" },

    { "id": "1820798", "side": "china", "htype": "event", "label": "Chinese company has the best AI model by Dec 31, 2026", "from": "2026-07-12", "role": "china_best" },
    { "id": "2873443", "side": "china", "htype": "event", "label": "Chinese company has a top-3 AI model by Dec 31, 2026", "from": "2026-07-12", "role": "china_top3" },
    { "id": "2873458", "side": "china", "htype": "event", "label": "Chinese company has a top-5 AI model by Dec 31, 2026", "from": "2026-07-12", "to": "2026-08-03",
      "note": "closed by Polymarket 2026-08-03, five months before its own deadline (resolved early); not returned by Gamma since" },
    { "id": "2873459", "side": "china", "htype": "event", "label": "Chinese company has a top-10 AI model by Dec 31, 2026", "from": "2026-07-12", "to": "2026-08-03",
      "note": "closed by Polymarket 2026-08-03, five months before its own deadline (resolved early); not returned by Gamma since" },
    { "id": "2431240", "side": "china", "htype": "event", "label": "Alibaba has the best Chinese AI model end of July 2026", "from": "2026-07-12", "to": "2026-08-01",
      "note": "resolved 2026-07-31 by its own terms" },
    { "id": "2431245", "side": "china", "htype": "event", "label": "DeepSeek has the best Chinese AI model end of July 2026", "from": "2026-07-12", "to": "2026-08-01",
      "note": "resolved 2026-07-31 by its own terms" },
    { "id": "2431244", "side": "china", "htype": "event", "label": "Z.ai has the best Chinese AI model end of July 2026", "from": "2026-07-12", "to": "2026-08-01",
      "note": "resolved 2026-07-31 by its own terms" },

    { "id": "609655",  "side": "macro", "htype": "event", "label": "US recession by end of 2026", "from": "2026-07-12", "role": "recession" },
    { "id": "3407418", "side": "macro", "htype": "event", "label": "US recession by end of 2027", "from": "2027-01-01", "role": "recession",
      "note": "like-for-like 2027 successor to 609655 (same question, next year); takes the macro family's recession leg over on 2027-01-01" },
    { "id": "616905",  "side": "macro", "htype": "event", "label": "3+ Fed rate cuts in 2026 (easing cycle)", "from": "2026-07-12", "role": "fed_cuts" },
    { "id": "616902",  "side": "macro", "htype": "event", "label": "0 Fed rate cuts in 2026 (tight stance)", "from": "2026-07-12" },
    { "id": "1192817", "side": "macro", "htype": "event", "label": "China 2026 GDP growth between 1-2% (slowdown)", "from": "2026-07-12" }
  ]
};
