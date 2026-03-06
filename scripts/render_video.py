def render_video(image_paths, audio_path, output_path, scene_weights=None, watermark_text="GhostEngine", style_name="default"):
    print(f"⚙️ [RENDERER] Executing Master Render Engine...")
    srt_path, ass_path, temp_concat, temp_merged = audio_path.replace(".wav", ".srt"), audio_path.replace(".wav", ".ass"), "concat_list.txt", "temp_merged_no_subs.mp4"
    if not srt_to_ass(srt_path, ass_path, get_style_config(style_name)): return False
    
    try:
        audio = AudioSegment.from_file(audio_path)
        total_dur = min(len(audio) / 1000.0, 59.0)
        if len(audio) / 1000.0 > 59.0:
            audio[:59000].fade_out(1500).export(audio_path, format="wav")
    except: return False

    clip_durs = [w * total_dur for w in scene_weights] if scene_weights else [total_dur / len(image_paths)] * len(image_paths)
    clip_files = []
    
    for i, img in enumerate(image_paths):
        clip_out = f"temp_anim_{i}.mp4"
        if create_ken_burns_clip(img, clip_durs[i], clip_out, index=i): clip_files.append(clip_out)

    with open(temp_concat, "w") as f:
        for c in clip_files: f.write(f"file '{c}'\n")

    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", temp_concat, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", temp_merged], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    # 🚨 METALLIC WATERMARK: Bold font, 25% transparency, silver hex color, black drop shadow for metallic depth.
    font_path = download_cinematic_font()
    safe_font = font_path.replace('\\', '/').replace(':', r'\:')
    safe_ass = ass_path.replace('\\', '/').replace(':', r'\:')
    
    watermark_filter = f",drawtext=fontfile='{safe_font}':text='{watermark_text}':fontcolor=0xD3D3D3@0.25:shadowcolor=0x000000@0.25:shadowx=3:shadowy=3:fontsize=60:x=(w-text_w)/2:y=h-250"
    
    subprocess.run(["ffmpeg", "-y", "-i", temp_merged, "-vf", f"ass='{safe_ass}'{watermark_filter}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "copy", output_path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    for f in clip_files + [temp_concat, temp_merged, ass_path]:
        if os.path.exists(f): os.remove(f)
    return True, total_dur, os.path.getsize(output_path) / (1024 * 1024)
