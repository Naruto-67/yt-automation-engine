# ================================================
# FILE: main.py (Excerpt - Update inside run_production_cycle)
# ================================================

        try:
            # 1. Script & Prompt Generation
            script_text, hook, image_prompts = generate_script(niche, topic)
            if not script_text or len(image_prompts) == 0:
                raise Exception("Script or Image Prompts returned empty.")

            # 2. Metadata Optimization
            metadata = generate_seo_metadata(niche, script_text)

            # 3. Voice & SRT Generation
            voice_success, provider = generate_audio(script_text, output_base=audio_base)
            if not voice_success:
                raise Exception("Voice/SRT generation failed.")
            print(f"✅ [VOICE] Audio secured via {provider}")

            # 4. Visual Sourcing (NEW MULTI-IMAGE LOGIC)
            # We now fetch 4 images instead of 1 background video
            image_paths = fetch_scene_images(image_prompts, base_filename=f"temp_scene_{success_count}")
            
            if len(image_paths) == 0:
                raise Exception("All visual generation engines failed.")
            print(f"✅ [VISUALS] Secured {len(image_paths)} scene images.")

            # 5. Master Render (Updated signature for Phase 4)
            render_success = render_video(image_paths, f"{audio_base}.wav", final_video)
            
            if not render_success:
                raise Exception("FFmpeg Master Render failed.")

            # 6. Vault Security (Skipped in Test Mode)
            # ... (Rest of main.py remains as defined in our previous step)
