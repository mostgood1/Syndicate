from numpy.random import sample


def debug_mlb_pipeline(selected_date=None):
    print("\n🔍 DEBUG MLB PIPELINE\n")

    # -------------------------
    # STEP 1 — SOURCE
    # -------------------------
    try:
        from syndicate.features.mlb.live_lens import read_latest_live_lens_page_context
        
        live_data = read_latest_live_lens_page_context(selected_date)
        if not live_data:
            print("❌ BREAK at SOURCE: live lens data is empty or missing")
        else:
            print("✅ SOURCE OK: live lens data loaded")
    except Exception as e:
        print(f"❌ BREAK at SOURCE: error loading live data → {e}")

    print("\n📁 CHECKING DATA SOURCE DETAILS")

    if live_data:
        try:
            if isinstance(live_data, dict):
                print("Live data keys:", list(live_data.keys()))
            elif isinstance(live_data, list):
                print("Live data length:", len(live_data))
            else:
                print("Live data type:", type(live_data))
        except Exception as e:
            print("Error inspecting live data:", e)
            
    # -------------------------
    # STEP 2 — CARDS LAYER (transform)
    # -------------------------
    try:
        from syndicate.features.mlb.cards import build_cards_page_context
        
        context = build_cards_page_context(selected_date)
        if not context:
            print("❌ BREAK at CARDS: context is empty")
        else:
            print("✅ CARDS OK: context built")

        # Check core sections
        games = context.get("games") or context.get("cards")
        if not games:
            print("❌ BREAK at CARDS: no games/cards in context")
        else:
            print(f"✅ CARDS OK: found {len(games)} games/cards")

    except Exception as e:
        print(f"❌ BREAK at CARDS: error building context → {e}")
        return

    # -------------------------
    # STEP 3 — LIVE DATA IN CONTEXT
    # -------------------------
    try:
        sample = games[0] if games else None

        if not sample:
            print("❌ BREAK: no sample game found")
        else:
            print("\n📦 SAMPLE GAME KEYS:")
            print(list(sample.keys()))

            # Check common live fields
            print("\n🔍 LIVE FIELD CHECK:")            
            if "live" in sample:
                print("✅ LIVE DATA ATTACHED (sample['live'])")
            elif "shared_is_live" in sample:
                print("✅ LIVE STATUS PRESENT")
            elif "gameLens" in sample:
                print("✅ GAME LENS DATA PRESENT")
            else:
                print("❌ No recognizable live fields found")

    except Exception as e:
        print(f"❌ BREAK at FIELD CHECK: {e}")

    # -------------------------
    # STEP 4 — FINAL CONTEXT OUTPUT
    # -------------------------
    print("\n✅ PIPELINE CHECK COMPLETE\n")