/* =====================================================================
   data.js — Composer data for the V.R World Media posting dashboard.
   ---------------------------------------------------------------------
   WHAT THIS IS:
   A plain JavaScript object (COMPOSER_DATA) holding the content helpers
   the Compose view uses: title formulas, hook templates, the thumbnail
   checklist, and per-platform character/hashtag limits.

   WHERE IT CAME FROM:
   Converted from the research content pack
   `phase2/app/data/composer_data.json` so this page works when opened
   straight from the file system (file://) with ZERO fetch() calls —
   fetch() is blocked on file:// in most browsers, so the data lives
   right here as a const.

   PHASE 2:
   When the Python backend exists, this same object can be served from
   an endpoint (e.g. GET /api/composer-data) and loaded with fetch().
   Until then, this static copy is the source of truth.
   ===================================================================== */

const COMPOSER_DATA = {
  "hook_templates": [
    "Nobody talks about this part of [topic].",
    "The [unexpected fact] about [topic] nobody mentions.",
    "Did you know that [counterintuitive fact]?",
    "Here's why [unexpected fact]...",
    "Stop doing [action] if you want [goal].",
    "This is why your [action] isn't working.",
    "3 mistakes killing your [results] right now.",
    "Everything you knew about [subject] is WRONG.",
    "Don't hate me, but [hard truth].",
    "You don't need [X]. You need [Y].",
    "It took me [X years] to learn this. I'll teach it in under 1 minute.",
    "Three months ago I had [starting point]. This is what changed.",
    "What would you do with an extra [amount/time]?",
    "If I woke up with [pain point] tomorrow and wanted [dream result]by [time], here's exactly what I'd do.",
    "POV: you're [identity] in 2026.",
    "I've been making this mistake for [time].",
    "The hidden [platform] setting that [industry] never mentions.",
    "How to get [result] in less than [time] without [pain].",
    "When [trigger] happens, do this instead.",
    "Nobody tells you this about [topic] — until now."
  ],
  "platform_limits": {
    "instagram": {
      "caption_max": 2200
    },
    "tiktok": {
      "caption_max": 2200,
      "hashtags_max": 100
    },
    "x": {
      "caption_max": 280,
      "hashtags_recommended_max": 4
    },
    "youtube": {
      "description_max": 5000,
      "title_max": 100
    }
  },
  "thumbnail_checklist": [
    "One clear focal point — max 3 competing elements (rule of thirds, generous negative space).",
    "Thumbnail text: 2-4 words (max 5). NEVER repeat the video title —complement it with a different angle.",
    "Text readable at 120px wide: bold condensed sans-serif,high-contrast fill + stroke/shadow.",
    "High contrast overall — dominant subject brighter OR darker thanthe background; grayscale-test it.",
    "Curiosity gap: show the setup, hide the payoff. Pattern interruptor bold statement.",
    "Pre-flight: could a stranger tell what it's about in 1 second at 320x180?",
    "Keep text out of the bottom-right corner (timestamp badge) and TikTok bottom ~20% (UI overlay).",
    "Thumbnail must match the video intro: title + thumbnail + first 30 seconds = one packaging unit.",
    "No misleading packaging — everything depicted must appear in the video, as depicted.",
    "Faceless: a curved arrow does the face's gaze-direction work; the concept OBJECT is the variable.",
    "Own your colors: same 2-3 color palette on every thumbnail for feed recognition.",
    "Font licensing clean: Google Fonts (OFL) only — no 'free for personal use' downloads.",
    "Rotate the layout every ~5th video: consistent palette/font,never a locked template.",
    "Produce 3 variants (expression / color / text) — test watch-timeshare, not CTR.",
    "Stylized AI imagery OK; photorealistic AI implying real events needs disclosure + honesty."
  ],
  "title_formulas": [
    "Forex Risk Management: The 1% Rule Explained in 9 Minutes",
    "I Backtested 5 Stop-Loss Rules on 10 Years of EUR/USD Data",
    "What Is Leverage? (And Why It Wipes Out Beginners)",
    "Position Sizing for Beginners: The Only Formula You Need",
    "Why 70-90% of Retail Traders Lose Money (The Data)",
    "Candlestick Basics: Reading Price Without Indicators",
    "Demo Trading for 90 Days: What I Actually Learned",
    "Spreads, Commissions & Slippage: The Hidden Costs of Trading",
    "Support and Resistance, Explained Like You're Five",
    "The Trading Journal Setup That Changed How I Learn",
    "Binary Options, Honestly: How They Work and Why Regulators Act",
    "5 Binary Options Scam Red Flags (Regulator Warnings, Sourced)",
    "Risk-Reward Ratios: The Math Most Beginners Skip",
    "What Happens When You Over-Leverage? (A Worked Example)",
    "How to Evaluate a Forex Broker: A Checklist",
    "How Odds Work: Implied Probability in 5 Minutes",
    "American vs Decimal vs Fractional Odds - Finally Explained",
    "What Is the Vig? The Hidden Fee in Every Bet",
    "Bankroll Management Basics (The Math, Not the Hype)",
    "Why 'Lock of the Day' Posts Are Lying to You",
    "Expected Value, Explained With Coin Flips",
    "How to Read a Tipster's Record Like a Skeptic",
    "NFL Key Numbers: Why 3 and 7 Matter to Oddsmakers",
    "Line Movement: What It Means (and Doesn't)",
    "5 Cognitive Biases That Drain Bettors' Bankrolls",
    "The Favorite-Longshot Bias, Explained",
    "Famous Bad Beats in Sports History",
    "How Sportsbooks Actually Set Odds",
    "Parlays: The Math the Hype Leaves Out",
    "Responsible Gambling: Setting Limits That Work",
    "GTA 6 Map Breakdown: Every Confirmed Location So Far",
    "10 Details You Missed in the GTA 6 Trailer",
    "GTA 6: All Confirmed Gameplay Features (Sourced)",
    "How Heists Could Work in GTA 6 [CONCEPT]",
    "GTA 6 Money Guide: [Method] Explained",
    "Every Hidden Collectible Found So Far",
    "GTA 6 Patch [X.X] Notes, Explained in 6 Minutes",
    "What Rockstar Has (and Hasn't) Confirmed About DLC [RUMOR]",
    "GTA 6 vs GTA 5: Map Size Compared",
    "The Fastest Legit Money Methods Right Now",
    "100% Completion Checklist: [Category]",
    "GTA 6's Economy, Explained",
    "5 Beginner Mistakes in GTA 6 Online",
    "New Update: Everything Worth Knowing This Week",
    "[CONCEPT] How a Casino Heist Could Work in GTA 6"
  ]
};

